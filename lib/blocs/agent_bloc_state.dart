import 'package:equatable/equatable.dart';

abstract class AgentEvent extends Equatable {
  @override
  List<Object?> get props => [];
}

/// Load a set of traces (or default ones) into the local display.
class LoadLocalTracesEvent extends AgentEvent {
  final List<Map<String, dynamic>> traces;
  LoadLocalTracesEvent({this.traces = const []});

  @override
  List<Object?> get props => [traces];
}

class ClearTracesEvent extends AgentEvent {}

class UpdateTracesEvent extends AgentEvent {
  final List<dynamic> traces;
  UpdateTracesEvent(this.traces);

  @override
  List<Object?> get props => [traces];
}

abstract class AgentState extends Equatable {
  @override
  List<Object?> get props => [];
}

class AgentInitial extends AgentState {}

class AgentPolling extends AgentState {
  final List<dynamic> traces;
  AgentPolling(this.traces);

  @override
  List<Object?> get props => [traces];
}

class AgentError extends AgentState {
  final String message;
  AgentError(this.message);

  @override
  List<Object?> get props => [message];
}
