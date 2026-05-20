import 'package:dio/dio.dart';
import 'package:ciro/services/data_service.dart';

class SirenaApiService {
  static final SirenaApiService _instance = SirenaApiService._internal();
  factory SirenaApiService() => _instance;

  late final Dio _dio;

  // Production backend on Hugging Face
  static const String _baseUrl = 'https://muhammadahsanmask-sirena-backend.hf.space/';

  SirenaApiService._internal() {
    _dio = Dio(
      BaseOptions(
        baseUrl: _baseUrl,
        connectTimeout: const Duration(seconds: 60),
        receiveTimeout: const Duration(seconds: 60), // Increased for cold starts
        headers: {'Content-Type': 'application/json'},
      ),
    );
  }

  /// Trigger the multi-agent pipeline using /ingest/signal
  Future<Map<String, dynamic>> ingestSignal({
    required String origin,
    required String destination,
    String? scenario,
  }) async {
    // Inject the exact city into the string so the backend doesn't default to Islamabad
    final zoneInfo = DataService().getZoneInfo(origin);
    final city = zoneInfo?['city'] ?? '';
    final finalOrigin = city.isNotEmpty && !origin.toLowerCase().contains(city.toLowerCase()) 
        ? '$origin, $city' 
        : origin;

    try {
      final response = await _dio.post(
        'api/ingest/signal',
        data: {
          'user_origin': finalOrigin,
          'user_destination': destination,
          if (scenario != null) 'scenario': scenario,
        },
      );
      
      return Map<String, dynamic>.from(response.data ?? {});
    } catch (e) {
      rethrow;
    }
  }

  /// Webhook: push a new alternate route to the app.
  Future<Map<String, dynamic>> updateRoute({
    required String alternateRoute,
    required String crisisLocation,
  }) async {
    try {
      final response = await _dio.post(
        'api/update-route',
        data: {
          'alternate_route': alternateRoute,
          'crisis_location': crisisLocation,
        },
      );
      return Map<String, dynamic>.from(response.data ?? {});
    } catch (e) {
      rethrow;
    }
  }

  Future<Map<String, dynamic>> sendAlert({
    required String alertText,
    required String crisisType,
  }) async {
    try {
      final response = await _dio.post(
        'api/send-alert',
        data: {'alert_text': alertText, 'crisis_type': crisisType},
      );
      return Map<String, dynamic>.from(response.data ?? {});
    } catch (e) {
      rethrow;
    }
  }

  Future<Map<String, dynamic>> getOutcome(String sessionId) async {
    try {
      final response = await _dio.get('api/outcome/$sessionId');
      return Map<String, dynamic>.from(response.data['outcome'] ?? {});
    } catch (e) {
      return {};
    }
  }
}
