from django.urls import path
from django.http import HttpResponse
import views
import health
import os

def hotel_map_home(request):
    """Serve the hotel map as the only page"""
    try:
        print(f"DEBUG: Attempting to serve hotel_map.html")
        print(f"DEBUG: Current working directory: {os.getcwd()}")
        print(f"DEBUG: __file__ directory: {os.path.dirname(__file__)}")
        
        # Read the hotel_map.html file
        file_path = os.path.join(os.path.dirname(__file__), 'hotel_map.html')
        print(f"DEBUG: Trying to read file at: {file_path}")
        print(f"DEBUG: File exists: {os.path.exists(file_path)}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        print(f"DEBUG: Successfully read {len(html_content)} characters")
        return HttpResponse(html_content, content_type='text/html')
    except FileNotFoundError as e:
        print(f"ERROR: FileNotFoundError: {e}")
        return HttpResponse(f"Hotel map not found at {file_path}", status=404)
    except Exception as e:
        print(f"ERROR: Unexpected error in hotel_map_home: {e}")
        import traceback
        traceback.print_exc()
        return HttpResponse(f"Error loading hotel map: {str(e)}", status=500)

urlpatterns = [
    path('', hotel_map_home, name='home'),  # ONLY hotel map - nothing else
    path('search/', views.GooglePlacesHotelSearchView.as_view(), name='places-search'),
    path('api/search/', views.ConsolidatedPlacesAPI.as_view(), name='api-places-search'),
    path('api/search/address/', views.AddressSearchAPI.as_view(), name='api-search-address'),
    path('api/search/location/', views.LocationSearchAPI.as_view(), name='api-search-location'),
    path('api/search/permission/', views.LocationPermissionAPI.as_view(), name='api-search-permission'),
    # Removed the problematic labor search route
    path('geocode/', views.GoogleGeocodingView.as_view(), name='geocode'),
    path('health/', health.HealthCheckView.as_view(), name='health-check'),
        path('api/location/', views.location_api, name='location_api'),
        path('api/latlng/', views.latlng_api, name='latlng_api'),
        path('api/address/', views.address_api, name='address_api'),
]