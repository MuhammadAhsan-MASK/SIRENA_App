import 'package:flutter/material.dart';
import 'package:ciro/services/data_service.dart';
import 'package:ciro/theme/app_theme.dart';
import 'package:go_router/go_router.dart';

class OutcomeScreen extends StatefulWidget {
  final String sessionId;
  final String? scenario;
  const OutcomeScreen({super.key, required this.sessionId, this.scenario});

  @override
  State<OutcomeScreen> createState() => _OutcomeScreenState();
}

class _OutcomeScreenState extends State<OutcomeScreen> {
  Map<String, String>? _metrics;

  @override
  void initState() {
    super.initState();
    _metrics = DataService().getScenarioMetrics(widget.scenario ?? 'Urban Flooding');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: CIROTheme.background,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        title: const Text('FINAL OUTCOME REPORT', style: TextStyle(fontSize: 14, letterSpacing: 2)),
      ),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          const Center(
            child: Icon(Icons.check_circle, color: CIROTheme.secondary, size: 72),
          ),
          const SizedBox(height: 16),
          const Center(
            child: Text('CRISIS CONTAINED',
                style: TextStyle(fontSize: 24, fontWeight: FontWeight.w900, color: Colors.white, letterSpacing: 1.5)),
          ),
          const SizedBox(height: 8),
          const Center(
            child: Text('SIRENA Agent Pipeline Execution Successful',
                style: TextStyle(color: CIROTheme.textDim, fontSize: 12)),
          ),
          const SizedBox(height: 32),
          _buildImpactSection(_metrics ?? {}),
          const SizedBox(height: 32),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              onPressed: () => context.go('/'),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.white10,
                padding: const EdgeInsets.symmetric(vertical: 16),
              ),
              child: const Text('BACK TO DASHBOARD'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildImpactSection(Map<String, String> metrics) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('IMPACT ANALYSIS', style: TextStyle(fontWeight: FontWeight.bold, letterSpacing: 1.2)),
        const SizedBox(height: 16),
        _buildImpactRow('Congestion Reduction', metrics['congestion_reduction'] ?? 'N/A', CIROTheme.primary),
        _buildImpactRow('Citizens Notified', metrics['citizens_notified'] ?? 'N/A', CIROTheme.secondary),
        _buildImpactRow('Response Time', metrics['response_time'] ?? 'N/A', Colors.white),
      ],
    );
  }

  Widget _buildImpactRow(String label, String value, Color color) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12.0),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: CIROTheme.textDim, fontSize: 14)),
          Text(value, style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 14)),
        ],
      ),
    );
  }
}



