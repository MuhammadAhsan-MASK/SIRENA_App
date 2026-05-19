import 'package:ciro/services/sirena_api_service.dart';

class CrisisRepository {
  final SirenaApiService _apiService;

  CrisisRepository({SirenaApiService? apiService})
      : _apiService = apiService ?? SirenaApiService();

  /// Sends the user's route to the live backend.
  /// Returns the full response map from /ingest/signal.
  Future<Map<String, dynamic>> ingestSignal({
    required String origin,
    required String destination,
  }) async {
    return await _apiService.ingestSignal(
      origin: origin,
      destination: destination,
    );
  }

  /// Pushes alternate routing info via webhook.
  Future<Map<String, dynamic>> updateRoute({
    required String alternateRoute,
    required String crisisLocation,
  }) async {
    return await _apiService.updateRoute(
      alternateRoute: alternateRoute,
      crisisLocation: crisisLocation,
    );
  }

  /// Dispatches an emergency alert via webhook.
  Future<Map<String, dynamic>> sendAlert({
    required String alertText,
    required String crisisType,
  }) async {
    return await _apiService.sendAlert(
      alertText: alertText,
      crisisType: crisisType,
    );
  }
}

