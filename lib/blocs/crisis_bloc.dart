import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:ciro/repositories/crisis_repository.dart';
import 'package:ciro/blocs/crisis_bloc_state.dart';

class CrisisBloc extends Bloc<CrisisEvent, CrisisState> {
  final CrisisRepository _repository;

  CrisisBloc({required CrisisRepository repository})
      : _repository = repository,
        super(CrisisInitial()) {
    on<IngestSignalEvent>(_onIngestSignal);
    on<SendAlertEvent>(_onSendAlert);
    on<UpdateRouteEvent>(_onUpdateRoute);
  }

  Future<void> _onIngestSignal(
      IngestSignalEvent event, Emitter<CrisisState> emit) async {
    emit(CrisisLoading());
    try {
      final response = await _repository.ingestSignal(
        origin: event.origin,
        destination: event.destination,
      );
      emit(SignalIngested(response));
    } catch (e) {
      emit(CrisisError('Signal ingestion failed: ${e.toString()}'));
    }
  }

  Future<void> _onSendAlert(
      SendAlertEvent event, Emitter<CrisisState> emit) async {
    emit(CrisisLoading());
    try {
      final response = await _repository.sendAlert(
        alertText: event.alertText,
        crisisType: event.crisisType,
      );
      emit(WebhookSuccess(action: 'send-alert', response: response));
    } catch (e) {
      emit(CrisisError('Alert failed: ${e.toString()}'));
    }
  }

  Future<void> _onUpdateRoute(
      UpdateRouteEvent event, Emitter<CrisisState> emit) async {
    emit(CrisisLoading());
    try {
      final response = await _repository.updateRoute(
        alternateRoute: event.alternateRoute,
        crisisLocation: event.crisisLocation,
      );
      emit(WebhookSuccess(action: 'update-route', response: response));
    } catch (e) {
      emit(CrisisError('Route update failed: ${e.toString()}'));
    }
  }
}

