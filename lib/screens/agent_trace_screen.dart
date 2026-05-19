import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:ciro/blocs/agent_bloc.dart';
import 'package:ciro/blocs/agent_bloc_state.dart';
import 'package:ciro/theme/app_theme.dart';

class AgentTraceScreen extends StatefulWidget {
  final String sessionId;
  const AgentTraceScreen({super.key, required this.sessionId});

  @override
  State<AgentTraceScreen> createState() => _AgentTraceScreenState();
}

class _AgentTraceScreenState extends State<AgentTraceScreen> {
  @override
  void initState() {
    super.initState();
    context.read<AgentBloc>().add(LoadLocalTracesEvent());
  }

  @override
  void dispose() {
    context.read<AgentBloc>().add(ClearTracesEvent());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: CIROTheme.background,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        title: const Text('AGENT BRAIN STREAM', style: TextStyle(fontSize: 14, letterSpacing: 2)),
      ),
      body: BlocBuilder<AgentBloc, AgentState>(
        builder: (context, state) {
          if (state is AgentPolling) {
            return Column(
              children: [
                Expanded(
                  child: ListView.builder(
                    padding: const EdgeInsets.all(16),
                    itemCount: state.traces.length,
                    itemBuilder: (context, index) {
                      final trace = state.traces[index];
                      return _buildTraceRow(trace);
                    },
                  ),
                ),
                if (state.traces.length >= 6)
                  Padding(
                    padding: const EdgeInsets.all(16.0),
                    child: SizedBox(
                      width: double.infinity,
                      child: ElevatedButton(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: CIROTheme.primary,
                          foregroundColor: Colors.black,
                          padding: const EdgeInsets.symmetric(vertical: 16),
                        ),
                        onPressed: () => Navigator.of(context).pop(),
                        child: const Text('BACK TO DASHBOARD', style: TextStyle(fontWeight: FontWeight.bold)),
                      ),
                    ),
                  ),
              ],
            );
          }
          return const Center(child: CircularProgressIndicator());
        },
      ),
    );
  }

  Widget _buildTraceRow(Map<String, dynamic> trace) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12.0),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('[LOG]', style: TextStyle(color: CIROTheme.primary.withOpacity(0.5), fontSize: 10, fontFamily: 'monospace')),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(trace['agent'] ?? '', style: const TextStyle(color: CIROTheme.primary, fontWeight: FontWeight.bold, fontSize: 11)),
                const SizedBox(height: 4),
                Text(trace['message'] ?? '', style: const TextStyle(color: CIROTheme.textBody, fontSize: 13)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

