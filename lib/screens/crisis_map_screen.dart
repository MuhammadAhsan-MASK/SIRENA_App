import 'package:flutter/material.dart';
import 'package:ciro/services/data_service.dart';
import 'package:ciro/theme/app_theme.dart';
import 'package:go_router/go_router.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';

class CrisisMapScreen extends StatefulWidget {
  final String sessionId;
  final String? scenario;
  const CrisisMapScreen({super.key, required this.sessionId, this.scenario});

  @override
  State<CrisisMapScreen> createState() => _CrisisMapScreenState();
}

class _CrisisMapScreenState extends State<CrisisMapScreen> {
  static const String mapboxToken = String.fromEnvironment('MAPBOX_TOKEN', defaultValue: '');
  Map<String, dynamic>? _sessionData;

  @override
  void initState() {
    super.initState();
    final dataSvc = DataService();
    final sid = dataSvc.getScenarioId(widget.scenario ?? 'Urban Flooding');
    // Provide some fallback mock data since DataService doesn't export raw scenarios
    _sessionData = {
      'data': {
        'detection': {
          'type': widget.scenario ?? 'Urban Flooding',
          'location': 'Central Hub',
        },
        'severity': {
          'level': 'HIGH',
        }
      }
    };
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: CIROTheme.background,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        title: const Text('TACTICAL CRISIS MAP', style: TextStyle(fontSize: 14, letterSpacing: 2)),
      ),
      body: _sessionData == null
          ? const Center(child: CircularProgressIndicator())
          : Builder(
              builder: (context) {
                final det = _sessionData!['data']?['detection'] ?? {};
                final sev = _sessionData!['data']?['severity'] ?? {};
                
                return Stack(
                  children: [
                    FlutterMap(
                      options: const MapOptions(
                        initialCenter: LatLng(33.6844, 73.0479),
                        initialZoom: 14.0,
                      ),
                      children: [
                        TileLayer(
                          urlTemplate: "https://api.mapbox.com/styles/v1/mapbox/dark-v11/tiles/{z}/{x}/{y}?access_token={accessToken}",
                          additionalOptions: const {
                            "accessToken": mapboxToken,
                          },
                        ),
                        MarkerLayer(
                          markers: [
                            Marker(
                              width: 100,
                              height: 60,
                              point: const LatLng(33.6844, 73.0479),
                              child: Column(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Container(
                                    padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
                                    decoration: BoxDecoration(
                                      color: CIROTheme.error.withOpacity(0.9),
                                      borderRadius: BorderRadius.circular(4),
                                      border: Border.all(color: Colors.white24),
                                    ),
                                    child: const Text('INCIDENT LOCATION', style: TextStyle(color: Colors.white, fontSize: 8, fontWeight: FontWeight.bold)),
                                  ),
                                  const Icon(Icons.location_on, color: CIROTheme.error, size: 28),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                    PositionRectanglePanel(
                      bottom: 20,
                      left: 20,
                      right: 20,
                      child: Container(
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(
                          color: CIROTheme.surface.withOpacity(0.9),
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(color: Colors.white10),
                        ),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(
                              'THREAT LEVEL: ${sev['level'] ?? 'CALCULATING...'}',
                              style: const TextStyle(color: CIROTheme.error, fontWeight: FontWeight.bold),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              'Type: ${det['type'] ?? 'N/A'} | Location: ${det['location'] ?? 'N/A'}',
                              style: const TextStyle(color: CIROTheme.textDim, fontSize: 10),
                            ),
                            const SizedBox(height: 12),
                            SizedBox(
                              width: double.infinity,
                              child: ElevatedButton(
                                onPressed: () => context.push('/plan/${widget.sessionId}'),
                                style: ElevatedButton.styleFrom(backgroundColor: CIROTheme.primary, foregroundColor: Colors.black),
                                child: const Text('VIEW RESPONSE PLAN', style: TextStyle(fontWeight: FontWeight.bold)),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                );
              },
            ),
    );
  }
}

class PositionRectanglePanel extends StatelessWidget {
  final Widget child;
  final double? top, bottom, left, right;
  const PositionRectanglePanel({super.key, required this.child, this.top, this.bottom, this.left, this.right});

  @override
  Widget build(BuildContext context) {
    return Positioned(
      top: top, bottom: bottom, left: left, right: right,
      child: child,
    );
  }
}
