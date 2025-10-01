
import os
import requests
import math
import hashlib
from datetime import datetime
from typing import Dict
from django.core.cache import cache
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json

@csrf_exempt
def location_api(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        category = data.get('category')
        # Replace with your actual logic
        return JsonResponse({'status': 'success', 'data': f'Places for lat={latitude}, lng={longitude}, category={category}'})
    return JsonResponse({'error': 'Invalid method'}, status=405)

@csrf_exempt
def latlng_api(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        category = data.get('category')
        # Replace with your actual logic
        return JsonResponse({'status': 'success', 'data': f'Places for lat={latitude}, lng={longitude}, category={category}'})
    return JsonResponse({'error': 'Invalid method'}, status=405)

@csrf_exempt
def address_api(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        address = data.get('address')
        category = data.get('category')
        # Replace with your actual logic
        return JsonResponse({'status': 'success', 'data': f'Places for address={address}, category={category}'})
    return JsonResponse({'error': 'Invalid method'}, status=405)


class GooglePlacesHotelSearchView(APIView):
    def get(self, request):
        """Support GET requests for /search/ endpoint (lat/lng required)."""
        lat = request.query_params.get('latitude')
        lng = request.query_params.get('longitude')
        category = self._get_category_from_request(request)
        if not (lat and lng):
            return Response({'error': 'latitude and longitude are required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            lat = float(lat)
            lng = float(lng)
        except ValueError:
            return Response({'error': 'Invalid latitude or longitude.'}, status=status.HTTP_400_BAD_REQUEST)
        area_size_param = request.query_params.get('area_size')
        area_size_meters = int(area_size_param) if area_size_param else 5000
        grid_size = int(request.query_params.get('grid_size', 3))
        overlap = float(request.query_params.get('overlap', 0.4))
        response_data = self.perform_search(lat=lat, lng=lng, category=category,
                                           area_size_meters=area_size_meters, grid_size=grid_size, overlap=overlap)
        return Response(response_data)

    def _make_request_with_retry(self, url: str, headers: Dict, json: Dict = None, method: str = 'get', max_retries: int = 1) -> Dict:
        """Make a request with minimal retry for faster response on Render"""
        for attempt in range(max_retries):
            try:
                if method.lower() == 'post':
                    response = requests.post(url, headers=headers, json=json, timeout=8)
                else:
                    response = requests.get(url, headers=headers, timeout=8)
                if response.status_code == 400:
                    error_msg = f"Bad request for {url}"
                    if hasattr(response, 'text'):
                        error_msg += f"\nResponse: {response.text}"
                    print(error_msg)
                    return {}
                response.raise_for_status()
                return response.json()
            except requests.RequestException as e:
                if attempt == max_retries - 1:
                    error_msg = f"Request failed after {max_retries} attempts for {url}: {str(e)}"
                    print(error_msg)
                    return {}
                if not hasattr(e, 'response') or (500 <= e.response.status_code < 600):
                    continue
                return {}
        return {}

    def format_place_data(self, place, details):
        full_address = place.get('formattedAddress', '')
        phone_number = details.get('nationalPhoneNumber') if details else None
        weekday_texts = details.get('currentOpeningHours', {}).get('weekdayDescriptions') if details else None
        current_opening_hours = details.get('currentOpeningHours', {}) if details else None
        is_open = current_opening_hours.get('openNow') if current_opening_hours else None
        return {
            'place_id': place.get('place_id') or place.get('id'),
            'name': place.get('displayName', {}).get('text', 'Unnamed Place'),
            'formatted_address': full_address,
            'location': {
                'latitude': place.get('location', {}).get('latitude'),
                'longitude': place.get('location', {}).get('longitude')
            },
            'rating': place.get('rating'),
            'user_ratings_total': place.get('userRatingCount', 0),
            'types': place.get('types', []),
            'phone_number': phone_number or "Not available",
            'website': details.get('websiteUri') if details else place.get('websiteUri') or "Not available",
            'price_level': place.get('priceLevel'),
            'business_status': place.get('businessStatus', 'OPERATIONAL'),
            'opening_hours': weekday_texts,
            'current_status': current_opening_hours,
            'is_open': is_open,
            'primary_type': place.get('types', ['PLACE'])[0].replace('_', ' ').title() if place.get('types') else 'Place',
            'short_address': place.get('shortFormattedAddress', full_address).split(',')[0],
            'has_phone': bool(phone_number)
        }

    def _sanitize_category(self, category: str) -> str:
        """Clean incoming category strings and provide a safe default."""
        if not category:
            return 'hotels'
        cat = str(category).strip()
        cat = cat.strip(';=').strip()
        return cat or 'hotels'

    def _get_category_from_request(self, request) -> str:
        """Robustly extract category from query params. Handles malformed keys like 'category;'."""
        category = request.query_params.get('category')
        if category:
            return self._sanitize_category(category)
        for key in request.query_params.keys():
            if not key:
                continue
            k = key.strip()
            if 'category' == k or k.startswith('category') or 'category' in k:
                val = request.query_params.get(key)
                if val:
                    return self._sanitize_category(val)
        return 'hotels'

    def perform_search(self, lat: float, lng: float, category: str = 'hotels', area_size_meters: int = 5000,
                       grid_size: int = 3, overlap: float = 0.4, max_results_per_cell: int = 20) -> Dict:
        try:
            keywords = [category]
            earth_radius = 6378137
            step_meters = area_size_meters * (1 - overlap) * 2 / grid_size
            def offset_lat(d):
                return (d / earth_radius) * (180 / math.pi)
            def offset_lng(d, lat0):
                return (d / (earth_radius * math.cos(math.pi * lat0 / 180))) * (180 / math.pi)
            places = {}
            url = 'https://places.googleapis.com/v1/places:searchText'
            api_key = os.getenv('GOOGLE_PLACES_API_KEY')
            search_headers = {
                'Content-Type': 'application/json',
                'X-Goog-Api-Key': api_key,
                'X-Goog-FieldMask': 'places.id,places.displayName,places.formattedAddress,places.location,'
                                  'places.rating,places.userRatingCount,places.types,places.nationalPhoneNumber,'
                                  'places.websiteUri,places.priceLevel,places.businessStatus,places.shortFormattedAddress,'
                                  'places.currentOpeningHours'
            }
            
            # Calculate search bounds for filtering results (much more lenient)
            half_area_km = area_size_meters / 1000  # Convert to km
            lat_delta = half_area_km / 111.32 * 2  # Double the range to be more inclusive
            lng_delta = half_area_km / (111.32 * math.cos(math.radians(lat))) * 2  # Double the range
            
            search_bounds = {
                'northeast': {
                    'lat': lat + lat_delta,
                    'lng': lng + lng_delta
                },
                'southwest': {
                    'lat': lat - lat_delta,
                    'lng': lng - lng_delta
                }
            }
            
            print(f"Searching for {category} near {lat}, {lng}")
            print(f"Search bounds: {search_bounds}")
            
            for keyword in keywords:
                # Improve the search query by adding context
                search_query = f"{keyword} in Odisha" if "odisha" in str(lat).lower() or "odisha" in str(lng).lower() else f"{keyword} near {lat},{lng}"
                
                for i in range(grid_size):
                    for j in range(grid_size):
                        try:
                            # Build a memcache-safe key by hashing the raw composite key
                            raw_key_base = f'places_search_{lat}_{lng}_{area_size_meters}_{category}_{keyword}_{i}_{j}'
                            cache_key = 'ps_' + hashlib.sha1(raw_key_base.encode('utf-8')).hexdigest()
                            cached_results = cache.get(cache_key)
                            if cached_results:
                                for place in cached_results:
                                    pid = place.get('place_id') or place.get('id')
                                    if pid and pid not in places:
                                        places[pid] = place  # Don't filter cached results
                                continue
                            offset_x = step_meters * (i - grid_size // 2)
                            offset_y = step_meters * (j - grid_size // 2)
                            lat_offset = offset_lat(offset_y)
                            lng_offset = offset_lng(offset_x, lat)
                            search_lat = lat + lat_offset
                            search_lng = lng + lng_offset
                            search_radius = int(step_meters * 0.7)
                            payload = {
                                'textQuery': search_query,
                                'locationBias': {
                                    'circle': {
                                        'center': {
                                            'latitude': search_lat,
                                            'longitude': search_lng
                                        },
                                        'radius': search_radius
                                    }
                                },
                                'maxResultCount': max_results_per_cell
                            }
                            print(f"Grid cell {i},{j}: Searching with query '{search_query}' at {search_lat},{search_lng}")
                            data = self._make_request_with_retry(
                                url=url,
                                headers=search_headers,
                                json=payload,
                                method='post'
                            )
                            if not data or 'places' not in data:
                                print(f"No data returned for grid cell {i},{j}")
                                try:
                                    cache.set(cache_key, [], timeout=3600)
                                except Exception as ce:
                                    print(f"Cache set failed for key {cache_key}: {ce}")
                                continue
                            cell_places = []
                            for place in data['places']:
                                place_id = place.get('place_id') or place.get('id')
                                if not place_id:
                                    continue
                                
                                # Extract location data
                                location = place.get('location', {})
                                place_lat = location.get('latitude')
                                place_lng = location.get('longitude')
                                
                                # Always include places, but mark if they're outside bounds
                                if place_id not in places:
                                    formatted_place = self.format_place_data(place, None)
                                    # Add a field to indicate if the place is within bounds
                                    if (place_lat and place_lng and 
                                        search_bounds['southwest']['lat'] <= place_lat <= search_bounds['northeast']['lat'] and
                                        search_bounds['southwest']['lng'] <= place_lng <= search_bounds['northeast']['lng']):
                                        formatted_place['within_search_bounds'] = True
                                    else:
                                        formatted_place['within_search_bounds'] = False
                                        # For places outside bounds, still include them if they seem relevant
                                        place_name = formatted_place.get('name', '').lower()
                                        place_address = formatted_place.get('formatted_address', '').lower()
                                        keyword_lower = keyword.lower()
                                        
                                        # Include if the place name or address contains the keyword or location hints
                                        if (keyword_lower in place_name or keyword_lower in place_address or
                                            'odisha' in place_name or 'odisha' in place_address):
                                            print(f"Including place outside bounds: {formatted_place.get('name')}")
                                        else:
                                            # Skip places that are clearly outside the region and not relevant
                                            continue
                                    
                                    places[place_id] = formatted_place
                                    cell_places.append(formatted_place)
                                    
                            try:
                                cache.set(cache_key, cell_places, timeout=3600)
                            except Exception as ce:
                                print(f"Cache set failed for key {cache_key}: {ce}")
                        except Exception as e:
                            print(f"Error in grid cell {i},{j} for keyword {keyword}: {str(e)}")
                            continue
            response_data = {
                'results': list(places.values()),
                'metadata': {
                    'total_results': len(places),
                    'search_parameters': {
                        'latitude': lat,
                        'longitude': lng,
                        'area_size_km': area_size_meters / 1000,
                        'cell_radius_m': int(step_meters / 2),
                        'keywords': keywords,
                        'grid_size': grid_size,
                        'overlap': overlap
                    },
                    'timestamp': datetime.now().isoformat()
                }
            }
            return response_data
        except Exception as e:
            print(f"perform_search error: {str(e)}")
            import traceback
            traceback.print_exc()
            return {"error": str(e)}

# Add new endpoints after all base classes
class AddressSearchAPI(GooglePlacesHotelSearchView):
    """Endpoint for searching by address and category."""
    def get(self, request):
        address = request.query_params.get('address')
        category = self._get_category_from_request(request)
        if not address:
            return Response({'error': 'Address is required.'}, status=status.HTTP_400_BAD_REQUEST)
        api_key = os.getenv('GOOGLE_PLACES_API_KEY')
        if not api_key:
            return Response({'error': 'Google API key is not configured'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        geocode_url = 'https://places.googleapis.com/v1/places:searchText'
        headers = {
            'Content-Type': 'application/json',
            'X-Goog-Api-Key': api_key,
            'X-Goog-FieldMask': 'places.location,places.formattedAddress,places.viewport'
        }
        # Improve the query to be more specific to India
        text_query = f"{address}, India"
        payload = {
            'textQuery': text_query,
            'regionCode': 'IN'
        }
        data = self._make_request_with_retry(url=geocode_url, headers=headers, json=payload, method='post')
        if not data or 'places' not in data or not data['places']:
            return Response({'error': 'Address geocoding failed or no location found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Try to find the most relevant result (prefer administrative areas)
        place = None
        for p in data["places"]:
            types = p.get("types", [])
            if "administrative_area_level_1" in types or "administrative_area_level_2" in types:
                place = p
                break
        
        # If no administrative area found, use the first result
        if not place:
            place = data['places'][0]
            
        location = place.get('location', {})
        lat = location.get('latitude')
        lng = location.get('longitude')
        if lat is None or lng is None:
            return Response({'error': 'Failed to obtain coordinates from address'}, status=status.HTTP_404_NOT_FOUND)
            
        # Get viewport bounds if available
        viewport = place.get('viewport', {})
        if viewport and viewport.get('high') and viewport.get('low'):
            # Calculate area size based on viewport
            ne_lat = viewport['high']['latitude']
            ne_lng = viewport['high']['longitude']
            sw_lat = viewport['low']['latitude']
            sw_lng = viewport['low']['longitude']
            
            # Calculate approximate area size in meters
            lat_diff = abs(ne_lat - sw_lat) * 111320  # meters per degree
            lng_diff = abs(ne_lng - sw_lng) * 111320 * math.cos(math.radians((ne_lat + sw_lat) / 2))
            area_size_meters = min(max(lat_diff, lng_diff), 50000)  # Cap at 50km
            # Ensure a minimum reasonable size
            if area_size_meters < 5000:
                area_size_meters = 15000
        else:
            # Default to 15000 meters
            area_size_meters = 15000
            
        area_size_param = request.query_params.get('area_size')
        area_size_meters = int(area_size_param) if area_size_param else area_size_meters
        grid_size = int(request.query_params.get('grid_size', 3))
        overlap = float(request.query_params.get('overlap', 0.4))
        response_data = self.perform_search(lat=lat, lng=lng, category=category,
                                           area_size_meters=area_size_meters, grid_size=grid_size, overlap=overlap)
        return Response(response_data)

class LocationSearchAPI(GooglePlacesHotelSearchView):
    """Endpoint for searching by latitude, longitude, and category."""
    def get(self, request):
        lat = request.query_params.get('latitude')
        lng = request.query_params.get('longitude')
        category = self._get_category_from_request(request)
        if not (lat and lng):
            return Response({'error': 'Latitude and longitude are required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            lat = float(lat)
            lng = float(lng)
        except ValueError:
            return Response({'error': 'Invalid latitude or longitude.'}, status=status.HTTP_400_BAD_REQUEST)
        area_size_param = request.query_params.get('area_size')
        area_size_meters = int(area_size_param) if area_size_param else 5000
        grid_size = int(request.query_params.get('grid_size', 3))
        overlap = float(request.query_params.get('overlap', 0.4))
        response_data = self.perform_search(lat=lat, lng=lng, category=category,
                                           area_size_meters=area_size_meters, grid_size=grid_size, overlap=overlap)
        return Response(response_data)

class LocationPermissionAPI(GooglePlacesHotelSearchView):
    """Endpoint for frontend location permission flow: accepts lat/lng and category after permission granted."""
    def get(self, request):
        lat = request.query_params.get('latitude')
        lng = request.query_params.get('longitude')
        category = self._get_category_from_request(request)
        if not (lat and lng):
            return Response({'error': 'Latitude and longitude are required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            lat = float(lat)
            lng = float(lng)
        except ValueError:
            return Response({'error': 'Invalid latitude or longitude.'}, status=status.HTTP_400_BAD_REQUEST)
        area_size_param = request.query_params.get('area_size')
        area_size_meters = int(area_size_param) if area_size_param else 5000
        grid_size = int(request.query_params.get('grid_size', 3))
        overlap = float(request.query_params.get('overlap', 0.4))
        response_data = self.perform_search(lat=lat, lng=lng, category=category,
                                           area_size_meters=area_size_meters, grid_size=grid_size, overlap=overlap)
        return Response(response_data)


class ConsolidatedPlacesAPI(GooglePlacesHotelSearchView):
    """A single API endpoint intended for frontend integration.

    Accepts either `address` (preferred) or `latitude`+`longitude`, plus `category` and optional grid params.
    Returns JSON with `results` and `metadata` ready for frontend rendering.
    """
    def get(self, request):
        try:
            address = request.query_params.get('address')
            lat = request.query_params.get('latitude')
            lng = request.query_params.get('longitude')
            category = self._get_category_from_request(request)

            area_size_param = request.query_params.get('area_size')
            area_size_meters = int(area_size_param) if area_size_param else 5000
            grid_size = int(request.query_params.get('grid_size', 3))
            overlap = float(request.query_params.get('overlap', 0.4))

            # Mode 1: address provided, use geocoding
            if address and not (lat and lng):
                api_key = os.getenv('GOOGLE_PLACES_API_KEY')
                if not api_key:
                    return Response({'error': 'Google API key is not configured'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                geocode_url = 'https://places.googleapis.com/v1/places:searchText'
                headers = {
                    'Content-Type': 'application/json',
                    'X-Goog-Api-Key': api_key,
                    'X-Goog-FieldMask': 'places.location,places.formattedAddress'
                }
                payload = {'textQuery': address}
                data = self._make_request_with_retry(url=geocode_url, headers=headers, json=payload, method='post')
                if not data or 'places' not in data or not data['places']:
                    return Response({'error': 'Address geocoding failed or no location found'}, status=status.HTTP_404_NOT_FOUND)
                place = data['places'][0]
                location = place.get('location', {})
                lat = location.get('latitude')
                lng = location.get('longitude')
                if lat is None or lng is None:
                    return Response({'error': 'Failed to obtain coordinates from address'}, status=status.HTTP_404_NOT_FOUND)

            # Mode 2: latitude and longitude provided, use directly
            elif lat and lng:
                try:
                    lat = float(lat)
                    lng = float(lng)
                except ValueError:
                    return Response({'error': 'Invalid latitude or longitude values.'}, status=status.HTTP_400_BAD_REQUEST)

            # Neither address nor lat/lng provided
            else:
                return Response({'error': 'Provide either address or latitude and longitude.'}, status=status.HTTP_400_BAD_REQUEST)

            response_data = self.perform_search(lat=lat, lng=lng, category=category,
                                                area_size_meters=area_size_meters, grid_size=grid_size, overlap=overlap)
            return Response(response_data)
        except Exception as e:
            print(f"Consolidated API error: {str(e)}")
            import traceback
            traceback.print_exc()
            return Response({'error': f'Consolidated search failed: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class GoogleGeocodingView(APIView):
    def get(self, request):
        address = request.query_params.get('address')
        region_code = request.query_params.get('region', 'IN')  # Default to 'IN' (India) but allow override
        
        if not address:
            return Response(
                {'error': 'Address parameter is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        api_key = os.getenv('GOOGLE_PLACES_API_KEY')
        if not api_key:
            return Response(
                {'error': 'Google API key is not configured'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        url = "https://places.googleapis.com/v1/places:searchText"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.formattedAddress,places.location,places.types,places.viewport"
        }
        # Improve the query to be more specific to India
        text_query = f"{address}, India"
        payload = {
            "textQuery": text_query,
            "regionCode": region_code
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            data = response.json()
            
            if "places" not in data or not data["places"]:
                return Response(
                    {"error": "No location found for this address"},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Try to find the most relevant result (prefer administrative areas)
            place = None
            for p in data["places"]:
                types = p.get("types", [])
                # Prefer administrative areas, then localities, then anything else
                if "administrative_area_level_1" in types:
                    place = p
                    break
                elif "administrative_area_level_2" in types and (not place or "administrative_area_level_1" not in place.get("types", [])):
                    place = p
                elif "locality" in types and (not place or ("administrative_area_level_1" not in place.get("types", []) and "administrative_area_level_2" not in place.get("types", []))):
                    place = p
                elif not place:
                    place = p
            
            location = place.get("location", {})
            
            # Use viewport for search area if available, otherwise use default
            viewport = place.get("viewport", {})
            if viewport and viewport.get("high") and viewport.get("low"):
                bounds = {
                    'northeast': {
                        'lat': viewport["high"]["latitude"],
                        'lng': viewport["high"]["longitude"]
                    },
                    'southwest': {
                        'lat': viewport["low"]["latitude"],
                        'lng': viewport["low"]["longitude"]
                    }
                }
                # Calculate area size based on viewport (in meters)
                ne_lat = viewport["high"]["latitude"]
                ne_lng = viewport["high"]["longitude"]
                sw_lat = viewport["low"]["latitude"]
                sw_lng = viewport["low"]["longitude"]
                
                # Calculate approximate area size in meters
                lat_diff = abs(ne_lat - sw_lat) * 111320  # meters per degree
                lng_diff = abs(ne_lng - sw_lng) * 111320 * math.cos(math.radians((ne_lat + sw_lat) / 2))
                area_size = min(max(lat_diff, lng_diff), 100000)  # Cap at 100km but ensure minimum reasonable size
                # If area is too small, use a default
                if area_size < 10000:
                    area_size = 25000  # 25km default for reasonable search
            else:
                # Default search area (25km radius for better coverage)
                area_size = 25000
                bounds = {
                    'northeast': {
                        'lat': location["latitude"] + 0.225,  # Approximately 25km
                        'lng': location["longitude"] + 0.225
                    },
                    'southwest': {
                        'lat': location["latitude"] - 0.225,
                        'lng': location["longitude"] - 0.225
                    }
                }

            response_data = {
                'results': [{
                    'formatted_address': place.get("formattedAddress", text_query),
                    'geometry': {
                        'location': {
                            'lat': location["latitude"],
                            'lng': location["longitude"]
                        },
                        'bounds': bounds
                    },
                    'area_info': {
                        'type': place.get("types", ["UNKNOWN"])[0],
                        'name': place.get("formattedAddress", text_query),
                        'grid_size': 3,  # Match backend default (3x3 grid)
                        'overlap': 0.4,  # Match backend default (40% overlap)
                        'area_size': int(area_size)
                    }
                }]
            }
            return Response(response_data)

        except Exception as e:
            print(f"Places API error: {str(e)}")  # Debug log
            return Response(
                {"error": f"Failed to geocode address: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
