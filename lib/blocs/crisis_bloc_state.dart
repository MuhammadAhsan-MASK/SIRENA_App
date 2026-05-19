import 'package:equatable/equatable.dart';

// ─── Events ───────────────────────────────────────────────────────────────────

abstract class CrisisEvent extends Equatable {
  @override
  List<Object?> get props => [];
}

/// Sends origin + destination to the live /ingest/signal endpoint.
class IngestSignalEvent extends CrisisEvent {
  final String origin;
  final String destination;
  IngestSignalEvent({required this.origin, required this.destination});

  @override
  List<Object?> get props => [origin, destination];
}

/// Dispatches an emergency alert via /api/send-alert.
class SendAlertEvent extends CrisisEvent {
  final String alertText;
  final String crisisType;
  SendAlertEvent({required this.alertText, required this.crisisType});

  @override
  List<Object?> get props => [alertText, crisisType];
}

/// Pushes a new alternate route via /api/update-route.
class UpdateRouteEvent extends CrisisEvent {
  final String alternateRoute;
  final String crisisLocation;
  UpdateRouteEvent({required this.alternateRoute, required this.crisisLocation});

  @override
  List<Object?> get props => [alternateRoute, crisisLocation];
}

// ─── States ───────────────────────────────────────────────────────────────────

abstract class CrisisState extends Equatable {
  @override
  List<Object?> get props => [];
}

class CrisisInitial extends CrisisState {}

class CrisisLoading extends CrisisState {}

/// Live backend responded to /ingest/signal successfully.
class SignalIngested extends CrisisState {
  final Map<String, dynamic> response;
  SignalIngested(this.response);

  @override
  List<Object?> get props => [response];
}

/// An alert or route-update webhook completed successfully.
class WebhookSuccess extends CrisisState {
  final String action;
  final Map<String, dynamic> response;
  WebhookSuccess({required this.action, required this.response});

  @override
  List<Object?> get props => [action, response];
}

class CrisisError extends CrisisState {
  final String message;
  CrisisError(this.message);

  @override
  List<Object?> get props => [message];
}
