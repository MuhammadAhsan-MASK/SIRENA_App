import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:ciro/services/data_service.dart';
import 'package:ciro/models/models.dart';
import 'package:ciro/theme/app_theme.dart';

class TacticalMapView extends StatelessWidget {
  final String scenario;
  final String? activeOrigin;
  final String? activeDestination;
  const TacticalMapView({super.key, required this.scenario, this.activeOrigin, this.activeDestination});

  static const String mapboxToken = String.fromEnvironment('MAPBOX_TOKEN', defaultValue: '');

  LatLng _getLatLng(double lat, double lng) => LatLng(lat, lng);

  @override
  Widget build(BuildContext context) {
    final scenarioId = DataService().getScenarioId(scenario);
    final data = DataService();
    
    // 1. Determine base city from scenario
    String visualCity = ['SCN-001', 'SCN-003', 'SCN-004'].contains(scenarioId) ? 'Islamabad' : 'Karachi';
    
    // 2. If signal is present, we might be switching cities!
    Map<String, dynamic>? activeZone;
    if (activeOrigin != null) {
      activeZone = data.getZoneInfo(activeOrigin!);
    } else if (activeDestination != null) {
      activeZone = data.getZoneInfo(activeDestination!);
    }

    if (activeZone != null && activeZone['city'] != null) {
      visualCity = activeZone['city'];
    }

    LatLng center = _getLatLng(
      visualCity == 'Islamabad' ? 33.6844 : 24.8607,
      visualCity == 'Islamabad' ? 73.0479 : 67.0011,
    );

    // If there is an active signal, snap exactly to it
    if (activeZone != null) {
      center = _getLatLng(activeZone['lat'] ?? activeZone['lat_center'], activeZone['lng'] ?? activeZone['lng_center']);
    }
    
    final roads = data.getRoads(scenarioId);
    final allResources = data.getResources();
    
    // Proximity Filtering Logic
    List<EmergencyResource> localResources;
    if (activeZone != null) {
      // If we have an active zone target, let's look for resources near it
      double targetLat = activeZone['lat'] ?? activeZone['lat_center'];
      double targetLng = activeZone['lng'] ?? activeZone['lng_center'];
      
      // Calculate a "Tactical Range" (approx 2km buffer)
      const double latBuffer = 0.018; 
      const double lngBuffer = 0.018;

      localResources = allResources.where((r) {
        return (r.lat >= targetLat - latBuffer && r.lat <= targetLat + latBuffer) &&
               (r.lng >= targetLng - lngBuffer && r.lng <= targetLng + lngBuffer);
      }).toList();
    } else {
      // Fallback to city-wide filter if no active signal
      localResources = allResources.where((r) => r.city == visualCity).take(10).toList();
    }

    List<Marker> markers = [];

    for (var road in roads) {
      markers.add(
        Marker(
          width: 100,
          height: 60,
          point: _getLatLng(road.latStart, road.lngStart),
          child: _buildCrisisMarker(context, road.roadName, Colors.red, Icons.add_road),
        ),
      );
    }

    // Show all resources
    for (var resource in localResources) {
       markers.add(
        Marker(
          width: 100,
          height: 60,
          point: _getLatLng(resource.lat, resource.lng),
          child: _buildCrisisMarker(context, resource.name, Colors.cyan, _getResourceIcon(resource.type)),
        ),
      );
    }

    if (activeOrigin != null) {
      final originZone = data.getZoneInfo(activeOrigin!);
      final lat = originZone?['lat'] ?? center.latitude + 0.01;
      final lng = originZone?['lng'] ?? center.longitude - 0.01;
      markers.add(
        Marker(
          width: 120,
          height: 60,
          point: _getLatLng(lat, lng),
          child: _buildCrisisMarker(context, 'SIGNAL: $activeOrigin', Colors.orange, Icons.my_location),
        ),
      );
    }
    
    if (activeDestination != null) {
      final destZone = data.getZoneInfo(activeDestination!);
      final lat = destZone?['lat'] ?? center.latitude - 0.01;
      final lng = destZone?['lng'] ?? center.longitude + 0.01;
      markers.add(
        Marker(
          width: 120,
          height: 60,
          point: _getLatLng(lat, lng),
          child: _buildCrisisMarker(context, 'SIGNAL: $activeDestination', Colors.orange, Icons.flag),
        ),
      );
    }

    return FlutterMap(
      key: ValueKey(scenarioId),
      options: MapOptions(
        initialCenter: center,
        initialZoom: 12.0,
      ),
      children: [
        TileLayer(
          urlTemplate: "https://api.mapbox.com/styles/v1/mapbox/dark-v11/tiles/{z}/{x}/{y}?access_token={accessToken}",
          additionalOptions: const {
            "accessToken": mapboxToken,
          },
        ),
        MarkerLayer(markers: markers),
      ],
    );
  }

  IconData _getResourceIcon(String type) {
    switch (type.toLowerCase()) {
      case 'ambulance': return Icons.medical_services;
      case 'police_unit': return Icons.local_police;
      case 'fire_brigade': return Icons.fire_truck;
      case 'hospital': return Icons.local_hospital;
      default: return Icons.emergency;
    }
  }

  Widget _buildCrisisMarker(BuildContext context, String label, Color color, IconData icon) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
          decoration: BoxDecoration(
            color: color.withOpacity(0.9),
            borderRadius: BorderRadius.circular(4),
            border: Border.all(color: Colors.white24),
          ),
          child: Text(
            label,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(color: Colors.white, fontSize: 8, fontWeight: FontWeight.bold),
          ),
        ),
        Icon(icon, color: color, size: 28),
      ],
    );
  }
}
