import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:ciro/blocs/agent_bloc_state.dart';

class AgentBloc extends Bloc<AgentEvent, AgentState> {
  AgentBloc() : super(AgentInitial()) {
    on<LoadLocalTracesEvent>(_onLoadLocal);
    on<ClearTracesEvent>(_onClear);
    on<UpdateTracesEvent>(_onUpdateTraces);
  }

  /// Loads a static list of agent trace messages for local display.
  void _onLoadLocal(LoadLocalTracesEvent event, Emitter<AgentState> emit) {
    final traces = event.traces.isNotEmpty
        ? event.traces
        : [
            {'agent': 'Signal Ingestion Agent', 'message': 'Scanning incoming data streams for crisis indicators...'},
            {'agent': 'Event Detection Agent', 'message': 'Correlating signals with historical crisis patterns...'},
            {'agent': 'Severity Analysis Agent', 'message': 'Estimating impact radius and affected population...'},
            {'agent': 'Response Planning Agent', 'message': 'Formulating optimal resource dispatch strategy...'},
            {'agent': 'Execution Simulation Agent', 'message': 'Simulating deployment of emergency units...'},
            {'agent': 'Outcome Reporting Agent', 'message': 'Compiling final metrics and outcome analysis...'},
          ];
    emit(AgentPolling(traces));
  }

  void _onClear(ClearTracesEvent event, Emitter<AgentState> emit) {
    emit(AgentInitial());
  }

  void _onUpdateTraces(UpdateTracesEvent event, Emitter<AgentState> emit) {
    emit(AgentPolling(event.traces));
  }
}
