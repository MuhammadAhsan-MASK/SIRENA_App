import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:go_router/go_router.dart';
import 'package:ciro/theme/app_theme.dart';
import 'package:ciro/blocs/crisis_bloc.dart';
import 'package:ciro/blocs/crisis_bloc_state.dart';
import 'package:ciro/repositories/crisis_repository.dart';
import 'package:ciro/widgets/agent_trace_panel.dart';
import 'package:ciro/widgets/tactical_map_view.dart';
import 'package:ciro/widgets/signal_feed_list.dart';
import 'package:ciro/services/data_service.dart';
import 'package:ciro/services/sirena_api_service.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  String _currentScenario = 'Urban Flooding';
  String? _activeSessionId;
  String? _activeOrigin;
  String? _activeDestination;
  @override
  void initState() {
    super.initState();
    DataService().loadDatasets();
  }

  @override
  Widget build(BuildContext context) {
    return BlocListener<CrisisBloc, CrisisState>(
      listener: (context, state) {
        if (state is CrisisLoading) {
          showDialog(
            context: context,
            barrierDismissible: false,
            builder: (context) => const Center(
              child: CircularProgressIndicator(),
            ),
          );
        } else if (state is SignalIngested) {
          // Dismiss loading dialog
          if (Navigator.of(context).canPop()) Navigator.of(context).pop();
          setState(() {
            _activeSessionId = state.response['session_id']?.toString();
          });
          _showSignalResultSheet(context, state.response);
        } else if (state is WebhookSuccess) {
          if (Navigator.of(context).canPop()) Navigator.of(context).pop();
          _showNotification(
            '✅ ${state.action}',
            state.response.toString(),
            Icons.check_circle,
            CIROTheme.secondary,
          );
        } else if (state is CrisisError) {
          if (Navigator.of(context).canPop()) Navigator.of(context).pop();
          _showNotification(
            '⚠ Backend Error',
            state.message,
            Icons.error,
            CIROTheme.error,
          );
        }
      },
      child: Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.security, color: CIROTheme.primary, size: 20),
                const SizedBox(width: 8),
                Flexible(
                  child: Text(
                    'SIRENA',
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                          fontSize: 22,
                          fontWeight: FontWeight.w900,
                          fontFamily: 'Roboto Mono',
                          color: Colors.white,
                        ),
                  ),
                ),
              ],
            ),
            Text(
              'SCENARIO: $_currentScenario',
              style: TextStyle(
                color: CIROTheme.textDim,
                fontSize: 10,
                fontFamily: 'Roboto Mono',
                letterSpacing: 1.1,
              ),
            ),
          ],
        ),
        actions: [
          PopupMenuButton<String>(
            icon: const Icon(Icons.settings_input_component, color: CIROTheme.primary),
            onSelected: (value) {
              setState(() => _currentScenario = value);
              _showIngestDialog(context, value);
            },
            itemBuilder: (context) => const [
              PopupMenuItem(value: 'Urban Flooding', child: Text('Scenario 1: Flooding')),
              PopupMenuItem(value: 'Heatwave Emergency', child: Text('Scenario 2: Heatwave')),
              PopupMenuItem(value: 'Road Blockage', child: Text('Scenario 3: Road Blockage')),
              PopupMenuItem(value: 'Road Accident', child: Text('Scenario 4: Accident')),
              PopupMenuItem(value: 'Infrastructure Failure', child: Text('Scenario 5: Infrastructure')),
            ],
          ),
          const SizedBox(width: 8),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            margin: const EdgeInsets.symmetric(vertical: 8),
            decoration: BoxDecoration(
              color: CIROTheme.error.withOpacity(0.1),
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: CIROTheme.error, width: 1),
            ),
            child: const Row(
              children: [
                Icon(Icons.warning, color: CIROTheme.error, size: 14),
                SizedBox(width: 6),
                Text(
                  'CRITICAL',
                  style: TextStyle(
                    color: CIROTheme.error,
                    fontWeight: FontWeight.bold,
                    fontSize: 10,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 16),
        ],
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(12.0), // Reduced slightly
          child: Column(
            children: [
              Expanded(
                flex: 5, // Increased from 3
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // Left: Signal Feed
                    Expanded(
                      flex: 1,
                      child: _buildPanel(
                        title: 'SIGNALS',
                        child: SignalFeedList(
                          scenario: _currentScenario,
                          activeOrigin: _activeOrigin,
                          activeDestination: _activeDestination,
                        ),
                      ),
                    ),
                    const SizedBox(width: 12),
                    // Center: Map View
                    Expanded(
                      flex: 2,
                      child: _buildPanel(
                        title: 'TACTICAL MAP',
                        child: TacticalMapView(
                          scenario: _currentScenario,
                          activeOrigin: _activeOrigin,
                          activeDestination: _activeDestination,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 12),
              // Bottom: Agent Thought Stream
              Expanded(
                flex: 2, // Adjusted ratio
                child: _buildPanel(
                  title: 'AGENT THOUGHT STREAM',
                  child: AgentTracePanel(
                    scenario: _currentScenario,
                    sessionId: _activeSessionId,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
      floatingActionButtonLocation: FloatingActionButtonLocation.endFloat,
      floatingActionButton: Padding(
        padding: const EdgeInsets.only(bottom: 20), // Lift slightly above bottom panel
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            FloatingActionButton.extended(
              heroTag: 'alert_btn',
              onPressed: () => _showSendAlertDialog(context),
              backgroundColor: CIROTheme.error,
              icon: const Icon(Icons.campaign, color: Colors.white, size: 18),
              label: const Text('ALERT', style: TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.bold)),
            ),
            const SizedBox(height: 8),
            FloatingActionButton.extended(
              heroTag: 'report_btn',
              onPressed: () => _showOutcomeReport(context),
              backgroundColor: CIROTheme.secondary,
              icon: const Icon(Icons.analytics, color: Colors.black, size: 18),
              label: const Text('REPORT', style: TextStyle(color: Colors.black, fontSize: 10, fontWeight: FontWeight.bold)),
            ),
          ],
        ),
      ),
      ),
    );
  }

  // ─── Ingest Signal Dialog ──────────────────────────────────────────────────
  void _showIngestDialog(BuildContext context, String scenarioName) {
    final originCtrl = TextEditingController(text: 'Saddar');
    final destCtrl = TextEditingController(text: 'Korangi');
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: CIROTheme.surface,
        title: Text('Run: $scenarioName',
            style: const TextStyle(color: CIROTheme.primary, fontSize: 14)),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('Enter route for agent analysis:',
                style: TextStyle(color: CIROTheme.textDim, fontSize: 12)),
            const SizedBox(height: 12),
            TextField(
              controller: originCtrl,
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(
                labelText: 'Origin',
                labelStyle: TextStyle(color: CIROTheme.textDim),
                enabledBorder: OutlineInputBorder(
                    borderSide: BorderSide(color: CIROTheme.primary)),
                focusedBorder: OutlineInputBorder(
                    borderSide: BorderSide(color: CIROTheme.primary, width: 2)),
              ),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: destCtrl,
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(
                labelText: 'Destination',
                labelStyle: TextStyle(color: CIROTheme.textDim),
                enabledBorder: OutlineInputBorder(
                    borderSide: BorderSide(color: CIROTheme.primary)),
                focusedBorder: OutlineInputBorder(
                    borderSide: BorderSide(color: CIROTheme.primary, width: 2)),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('CANCEL', style: TextStyle(color: CIROTheme.textDim)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: CIROTheme.primary),
            onPressed: () {
              Navigator.pop(ctx);
              setState(() {
                _activeOrigin = originCtrl.text.trim();
                _activeDestination = destCtrl.text.trim();
              });
              context.read<CrisisBloc>().add(IngestSignalEvent(
                origin: originCtrl.text.trim(),
                destination: destCtrl.text.trim(),
              ));
            },
            child: const Text('ANALYSE', style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
  }

  // ─── Signal Result Bottom Sheet ───────────────────────────────────────────
  void _showSignalResultSheet(BuildContext context, Map<String, dynamic> resp) {
    showModalBottomSheet(
      context: context,
      backgroundColor: CIROTheme.surface,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => DraggableScrollableSheet(
        initialChildSize: 0.55,
        maxChildSize: 0.9,
        minChildSize: 0.4,
        expand: false,
        builder: (_, ctrl) => Padding(
          padding: const EdgeInsets.all(24),
          child: ListView(
            controller: ctrl,
            children: [
              const Text('🛰 AGENT RESPONSE',
                  style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.bold,
                      color: CIROTheme.primary,
                      letterSpacing: 1.4)),
              const SizedBox(height: 4),
              const Text('Live backend pipeline result',
                  style: TextStyle(fontSize: 11, color: CIROTheme.textDim)),
              const Divider(color: Colors.white12, height: 24),
              ...resp.entries.map((e) => Padding(
                    padding: const EdgeInsets.symmetric(vertical: 5),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('${e.key}: ',
                            style: const TextStyle(
                                color: CIROTheme.primary,
                                fontWeight: FontWeight.bold,
                                fontSize: 12,
                                fontFamily: 'Roboto Mono')),
                        Expanded(
                          child: Text(
                            e.value.toString(),
                            style: const TextStyle(
                                color: Colors.white70, fontSize: 12),
                          ),
                        ),
                      ],
                    ),
                  )),
              const SizedBox(height: 24),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: () => Navigator.pop(ctx),
                  style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.white10,
                      padding: const EdgeInsets.symmetric(vertical: 14)),
                  child: const Text('CLOSE'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  // ─── Send Alert Dialog ────────────────────────────────────────────────────
  void _showSendAlertDialog(BuildContext context) {
    final alertCtrl = TextEditingController(
        text: 'Critical flooding detected. Evacuate area immediately.');
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: CIROTheme.surface,
        title: const Text('Send Emergency Alert',
            style: TextStyle(color: CIROTheme.error, fontSize: 14)),
        content: TextField(
          controller: alertCtrl,
          maxLines: 3,
          style: const TextStyle(color: Colors.white),
          decoration: const InputDecoration(
            labelText: 'Alert Message',
            labelStyle: TextStyle(color: CIROTheme.textDim),
            enabledBorder: OutlineInputBorder(
                borderSide: BorderSide(color: CIROTheme.error)),
            focusedBorder: OutlineInputBorder(
                borderSide: BorderSide(color: CIROTheme.error, width: 2)),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('CANCEL', style: TextStyle(color: CIROTheme.textDim)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: CIROTheme.error),
            onPressed: () {
              Navigator.pop(ctx);
              context.read<CrisisBloc>().add(SendAlertEvent(
                alertText: alertCtrl.text.trim(),
                crisisType: _currentScenario,
              ));
            },
            child: const Text('DISPATCH', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
  }

  void _showOutcomeReport(BuildContext context) {
    showModalBottomSheet(
      context: context,
      backgroundColor: CIROTheme.surface,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) {
        return FutureBuilder<Map<String, dynamic>>(
          future: _activeSessionId != null 
              ? SirenaApiService().getOutcome(_activeSessionId!)
              : Future.value(DataService().getScenarioMetrics(_currentScenario) ?? {}),
          builder: (context, snapshot) {
            // Handle loading state
            if (snapshot.connectionState == ConnectionState.waiting) {
              return const SizedBox(
                height: 300,
                child: Center(child: CircularProgressIndicator(color: CIROTheme.primary)),
              );
            }
            
            // Handle error or empty data with a fallback to local DataService
            final Map<String, dynamic> metrics = (snapshot.hasData && snapshot.data!.isNotEmpty)
                ? snapshot.data!
                : DataService().getScenarioMetrics(_currentScenario) ?? {
                    'congestion_reduction': '74%',
                    'response_time': '18 min',
                    'citizens_alerted': '1,247',
                  };
                  
            return DraggableScrollableSheet(
              initialChildSize: 0.6,
              maxChildSize: 0.9,
              minChildSize: 0.4,
              expand: false,
              builder: (BuildContext context, ScrollController scrollController) {
                return Container(
                  padding: const EdgeInsets.all(24),
                  child: ListView(
                    controller: scrollController,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Text(
                                'SIRENA OUTCOME REPORT',
                                style: TextStyle(
                                  fontSize: 18,
                                  fontWeight: FontWeight.bold,
                                  color: CIROTheme.primary,
                                ),
                              ),
                              const Text(
                                'From Signal to Safety — Automatically',
                                style: TextStyle(fontSize: 10, color: CIROTheme.textDim),
                              ),
                            ],
                          ),
                          if (_activeSessionId != null)
                             Container(
                               padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                               decoration: BoxDecoration(
                                 color: CIROTheme.secondary.withOpacity(0.1),
                                 borderRadius: BorderRadius.circular(4),
                               ),
                               child: const Text('LIVE', style: TextStyle(color: CIROTheme.secondary, fontSize: 8, fontWeight: FontWeight.bold)),
                             ),
                        ],
                      ),
                      const SizedBox(height: 20),
                      Row(
                        children: [
                          _buildStatCard('BEFORE', 'Heavy Traffic', Icons.traffic, CIROTheme.error),
                          const SizedBox(width: 12),
                          _buildStatCard('AFTER', 'Clear Flow', Icons.check_circle, CIROTheme.secondary),
                        ],
                      ),
                      const SizedBox(height: 24),
                      const Text(
                        'IMPACT METRICS',
                        style: TextStyle(fontSize: 14, fontWeight: FontWeight.bold, letterSpacing: 1.2),
                      ),
                      const SizedBox(height: 12),
                      _buildMetricLine('Congestion Reduction', metrics['congestion_reduction']?.toString() ?? '74%'),
                      _buildMetricLine('Response Time', metrics['response_time']?.toString() ?? '18 min'),
                      _buildMetricLine('Citizens Notified', metrics['citizens_alerted']?.toString() ?? metrics['citizens_notified']?.toString() ?? '1,247'),
                      _buildMetricLine('Tactical Deployment', 'Success'),
                      const SizedBox(height: 32),
                      SizedBox(
                        width: double.infinity,
                        child: ElevatedButton(
                          onPressed: () => Navigator.pop(context),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: Colors.white10,
                            padding: const EdgeInsets.symmetric(vertical: 16),
                          ),
                          child: const Text('CLOSE REPORT'),
                        ),
                      ),
                    ],
                  ),
                );
              },
            );
          }
        );
      },
    );
  }

  Widget _buildStatCard(String label, String value, IconData icon, Color color) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: Colors.white.withOpacity(0.05),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: color.withOpacity(0.3)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(label, style: const TextStyle(fontSize: 10, color: CIROTheme.textDim)),
            const SizedBox(height: 8),
            Icon(icon, color: color, size: 24),
            const SizedBox(height: 8),
            Flexible(
              child: Text(
                value,
                textAlign: TextAlign.center,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 11),
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _showNotification(String title, String message, IconData icon, Color color) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        duration: const Duration(seconds: 3),
        backgroundColor: Colors.transparent,
        elevation: 0,
        content: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: CIROTheme.surface,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: color.withOpacity(0.5)),
            boxShadow: [
              BoxShadow(color: color.withOpacity(0.1), blurRadius: 10, spreadRadius: 2),
            ],
          ),
          child: Row(
            children: [
              Icon(icon, color: color),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(title, style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 13)),
                    Text(message, style: const TextStyle(color: Colors.white, fontSize: 11)),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
  Widget _buildMetricLine(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4.0),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Expanded(child: Text(label, style: const TextStyle(color: CIROTheme.textDim, fontSize: 13))),
          const SizedBox(width: 8),
          Text(value, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 13)),
        ],
      ),
    );
  }

  Widget _buildPanel({required String title, required Widget child}) {
    return Container(
      decoration: BoxDecoration(
        color: CIROTheme.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            decoration: const BoxDecoration(
              border: Border(bottom: BorderSide(color: Colors.white10)),
            ),
            child: Text(
              title,
              style: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.bold,
                color: CIROTheme.primary,
                letterSpacing: 1.5,
              ),
            ),
          ),
          Expanded(child: child),
        ],
      ),
    );
  }

}
