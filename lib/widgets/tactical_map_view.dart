import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:ciro/services/data_service.dart';
import 'package:ciro/models/models.dart';
import 'package:ciro/theme/app_theme.dart';

import 'package:dio/dio.dart';

class TacticalMapView extends StatefulWidget {
  final String scenario;
  final String? activeOrigin;
  final String? activeDestination;
  const TacticalMapView({super.key, required this.scenario, this.activeOrigin, this.activeDestination});

  @override
  State<TacticalMapView> createState() => _TacticalMapViewState();
}

class _TacticalMapViewState extends State<TacticalMapView> {
  static const String mapboxToken = String.fromEnvironment('MAPBOX_TOKEN', defaultValue: '');

  List<Polyline> _polylines = [];
  bool _isLoadingRoutes = false;
  String _etaMessage = '';

  LatLng _getLatLng(double lat, double lng) => LatLng(lat, lng);

  @override
  void initState() {
    super.initState();
    _fetchRoutes();
  }

  @override
  void didUpdateWidget(TacticalMapView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.scenario != widget.scenario || 
        oldWidget.activeOrigin != widget.activeOrigin ||
        oldWidget.activeDestination != widget.activeDestination) {
      _fetchRoutes();
    }
  }

  Future<void> _fetchRoutes() async {
    setState(() {
      _isLoadingRoutes = true;
      _polylines = [];
    });

    final scenarioId = DataService().getScenarioId(widget.scenario);
    final roads = DataService().getRoads(scenarioId);
    List<Polyline> newPolylines = [];
    final dio = Dio();

    for (var road in roads) {
      try {
        // 1. Fetch exact real road path for the blocked section
        final url1 = 'https://api.mapbox.com/directions/v5/mapbox/driving/${road.lngStart},${road.latStart};${road.lngEnd},${road.latEnd}?geometries=geojson&access_token=$mapboxToken';
        final res1 = await dio.get(url1);
        if (res1.statusCode == 200) {
          List<dynamic> coords1 = res1.data['routes'][0]['geometry']['coordinates'];
          List<LatLng> blockedPoints = coords1.map((c) => LatLng((c[1] as num).toDouble(), (c[0] as num).toDouble())).toList();
          newPolylines.add(Polyline(
            points: blockedPoints,
            color: Colors.red.withOpacity(0.8),
            strokeWidth: 5.0,
          ));
        }

        // 2. Fetch diversion route bypassing the road by passing through a waypoint
        final midLng = road.lngStart + 0.005;
        final midLat = road.latStart + 0.005;
        final url2 = 'https://api.mapbox.com/directions/v5/mapbox/driving/${road.lngStart},${road.latStart};$midLng,$midLat;${road.lngEnd},${road.latEnd}?geometries=geojson&access_token=$mapboxToken';
        final res2 = await dio.get(url2);
        if (res2.statusCode == 200) {
          List<dynamic> coords2 = res2.data['routes'][0]['geometry']['coordinates'];
          List<LatLng> diversionPoints = coords2.map((c) => LatLng((c[1] as num).toDouble(), (c[0] as num).toDouble())).toList();
          newPolylines.add(Polyline(
            points: diversionPoints,
            color: Colors.greenAccent.withOpacity(0.9),
            strokeWidth: 4.0,
          ));
        }
      } catch (e) {
         // Fallback to straight line
         newPolylines.add(Polyline(
            points: [_getLatLng(road.latStart, road.lngStart), _getLatLng(road.latEnd, road.lngEnd)],
            color: Colors.red, strokeWidth: 5.0,
         ));
      }
    }

    // 3. Fetch Full Navigation Route connecting Origin to Destination
    if (widget.activeOrigin != null && widget.activeDestination != null && widget.activeOrigin!.isNotEmpty && widget.activeDestination!.isNotEmpty) {
      final originZone = DataService().getZoneInfo(widget.activeOrigin!);
      final destZone = DataService().getZoneInfo(widget.activeDestination!);
      if (originZone != null && destZone != null) {
        final double latOrigin = originZone['lat'] ?? originZone['lat_center'];
        final double lngOrigin = originZone['lng'] ?? originZone['lng_center'];
        final double latDest = destZone['lat'] ?? destZone['lat_center'];
        final double lngDest = destZone['lng'] ?? destZone['lng_center'];
        
        try {
          final navUrl = 'https://api.mapbox.com/directions/v5/mapbox/driving/$lngOrigin,$latOrigin;$lngDest,$latDest?geometries=geojson&access_token=$mapboxToken';
          final navRes = await dio.get(navUrl);
          if (navRes.statusCode == 200) {
            List<dynamic> coordsNav = navRes.data['routes'][0]['geometry']['coordinates'];
            List<LatLng> navPoints = coordsNav.map((c) => LatLng((c[1] as num).toDouble(), (c[0] as num).toDouble())).toList();
            
            double durationSecs = (navRes.data['routes'][0]['duration'] as num).toDouble();
            int etaMin = (durationSecs / 60).ceil();
            _etaMessage = "Navigating to ${widget.activeDestination} — ETA ~$etaMin min";
            
            // Insert at the beginning so it draws BEHIND the red blockages and green diversions
            newPolylines.insert(0, Polyline(
              points: navPoints,
              color: Colors.blueAccent.withOpacity(0.5),
              strokeWidth: 6.0,
            ));
          }
        } catch (e) {
          // ignore navigation mapping on failure
        }
      }
    }

    if (mounted) {
      setState(() {
        _polylines = newPolylines;
        _isLoadingRoutes = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final scenarioId = DataService().getScenarioId(widget.scenario);
    final data = DataService();
    
    // 1. Determine base city from scenario
    String visualCity = ['SCN-001', 'SCN-003', 'SCN-004'].contains(scenarioId) ? 'Islamabad' : 'Karachi';
    
    // 2. Identify active zones
    Map<String, dynamic>? originZone;
    Map<String, dynamic>? destZone;
    if (widget.activeOrigin != null) originZone = data.getZoneInfo(widget.activeOrigin!);
    if (widget.activeDestination != null) destZone = data.getZoneInfo(widget.activeDestination!);

    if (originZone != null && originZone['city'] != null) {
      visualCity = originZone['city'];
    }

    // Default center
    LatLng center = _getLatLng(
      visualCity == 'Islamabad' ? 33.6844 : 24.8607,
      visualCity == 'Islamabad' ? 73.0479 : 67.0011,
    );

    // If we have both, focus the camera in the exact middle!
    if (originZone != null && destZone != null) {
      double latOrigin = originZone['lat'] ?? originZone['lat_center'];
      double lngOrigin = originZone['lng'] ?? originZone['lng_center'];
      double latDest = destZone['lat'] ?? destZone['lat_center'];
      double lngDest = destZone['lng'] ?? destZone['lng_center'];
      center = _getLatLng((latOrigin + latDest) / 2, (lngOrigin + lngDest) / 2);
    } else if (originZone != null) {
      center = _getLatLng(originZone['lat'] ?? originZone['lat_center'], originZone['lng'] ?? originZone['lng_center']);
    }
    
    final roads = data.getRoads(scenarioId);
    final allResources = data.getResources();
    
    List<EmergencyResource> localResources;
    if (originZone != null) {
      double targetLat = originZone['lat'] ?? originZone['lat_center'];
      double targetLng = originZone['lng'] ?? originZone['lng_center'];
      const double latBuffer = 0.050; // expanded tactical range
      const double lngBuffer = 0.050;
      localResources = allResources.where((r) {
        return (r.lat >= targetLat - latBuffer && r.lat <= targetLat + latBuffer) &&
               (r.lng >= targetLng - lngBuffer && r.lng <= targetLng + lngBuffer);
      }).toList();
    } else {
      localResources = allResources.where((r) => r.city == visualCity).take(10).toList();
    }

    List<Marker> markers = [];

    for (var road in roads) {
      markers.add(
        Marker(
          width: 160, height: 70,
          point: _getLatLng(road.latStart, road.lngStart),
          child: _buildCrisisMarker(context, "${road.roadName} (BLOCKED)", Colors.red, Icons.block),
        ),
      );
      markers.add(
        Marker(
          width: 160, height: 70,
          point: _getLatLng(road.latStart + 0.005, road.lngStart + 0.005), // Midpoint geometry shift
          child: _buildCrisisMarker(context, "DETOUR", Colors.green, Icons.alt_route),
        ),
      );
    }

    for (var resource in localResources) {
       markers.add(
        Marker(
          width: 160, height: 70,
          point: _getLatLng(resource.lat, resource.lng),
          child: _buildCrisisMarker(context, resource.name, Colors.cyan, _getResourceIcon(resource.type)),
        ),
      );
    }

    if (originZone != null) {
      final lat = originZone['lat'] ?? originZone['lat_center'];
      final lng = originZone['lng'] ?? originZone['lng_center'];
      markers.add(Marker(
        width: 180, height: 90,
        point: _getLatLng(lat, lng),
        child: _buildRouteEndpointMarker(context, 'START\n${widget.activeOrigin}', Colors.blueAccent, Icons.trip_origin),
      ));
    }
    
    if (destZone != null) {
      final lat = destZone['lat'] ?? destZone['lat_center'];
      final lng = destZone['lng'] ?? destZone['lng_center'];
      markers.add(Marker(
        width: 180, height: 90,
        point: _getLatLng(lat, lng),
        child: _buildRouteEndpointMarker(context, 'FINISH\n${widget.activeDestination}', Colors.indigo, Icons.location_on),
      ));
    }

    return Stack(
      children: [
        FlutterMap(
          key: ValueKey('${scenarioId}_${widget.activeOrigin}_${widget.activeDestination}'),
          options: MapOptions(
            initialCenter: center,
            initialZoom: originZone != null && destZone != null ? 11.5 : 12.0,
          ),
          children: [
            TileLayer(
              urlTemplate: "https://api.mapbox.com/styles/v1/mapbox/streets-v12/tiles/{z}/{x}/{y}?access_token={accessToken}",
              additionalOptions: const {"accessToken": mapboxToken},
            ),
            if (_polylines.isNotEmpty) PolylineLayer(polylines: _polylines),
            MarkerLayer(markers: markers),
          ],
        ),
        if (_isLoadingRoutes)
          const Positioned(
            top: 16, right: 16,
            child: CircularProgressIndicator(color: CIROTheme.primary),
          ),

      ],
    );
  }

  Widget _buildRouteEndpointMarker(BuildContext context, String label, Color color, IconData icon) {
    return FittedBox(
      fit: BoxFit.scaleDown,
      child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          constraints: const BoxConstraints(maxWidth: 160),
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
          decoration: BoxDecoration(
            color: color,
            borderRadius: BorderRadius.circular(6),
            boxShadow: const [BoxShadow(color: Colors.black26, blurRadius: 4, offset: Offset(0, 2))],
          ),
          child: Text(
            label,
            textAlign: TextAlign.center,
            style: const TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.w900),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
        ),
        Icon(icon, color: color, size: 36, shadows: const [Shadow(color: Colors.black45, blurRadius: 4)]),
      ],
     ),
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
    return FittedBox(
      fit: BoxFit.scaleDown,
      child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          constraints: const BoxConstraints(maxWidth: 140),
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
          decoration: BoxDecoration(
            color: color.withOpacity(0.9),
            borderRadius: BorderRadius.circular(4),
            border: Border.all(color: Colors.white24),
          ),
          child: Text(
            label,
            overflow: TextOverflow.ellipsis,
            maxLines: 2,
            style: const TextStyle(color: Colors.white, fontSize: 8, fontWeight: FontWeight.bold),
          ),
        ),
        Icon(icon, color: color, size: 28),
      ],
     ),
    );
  }
}
