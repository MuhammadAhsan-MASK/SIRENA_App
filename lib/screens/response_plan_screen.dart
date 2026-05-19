import 'package:flutter/material.dart';
import 'package:ciro/services/data_service.dart';
import 'package:ciro/models/models.dart';
import 'package:ciro/theme/app_theme.dart';

class ResponsePlanScreen extends StatefulWidget {
  final String sessionId;
  final String? scenario;
  const ResponsePlanScreen({super.key, required this.sessionId, this.scenario});

  @override
  State<ResponsePlanScreen> createState() => _ResponsePlanScreenState();
}

class _ResponsePlanScreenState extends State<ResponsePlanScreen> {
  List<ResponseAction> _actions = [];

  @override
  void initState() {
    super.initState();
    final scenarioId = DataService().getScenarioId(widget.scenario ?? 'Urban Flooding');
    _actions = DataService().getActions(scenarioId);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: CIROTheme.background,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        title: const Text('PROPOSED RESPONSE PLAN', style: TextStyle(fontSize: 14, letterSpacing: 2)),
      ),
      body: _actions.isEmpty
          ? const Center(child: Text('No actions found.', style: TextStyle(color: CIROTheme.textDim)))
          : Column(
              children: [
                Expanded(
                  child: ListView.builder(
                    padding: const EdgeInsets.all(16),
                    itemCount: _actions.length,
                    itemBuilder: (context, index) {
                      final action = _actions[index];
                      return _buildActionCard(
                        action.actionName,
                        action.description,
                        Icons.emergency,
                        CIROTheme.secondary,
                      );
                    },
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.all(16.0),
                  child: SizedBox(
                    width: double.infinity,
                    child: ElevatedButton(
                      onPressed: () => Navigator.of(context).pop(),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: CIROTheme.secondary,
                        foregroundColor: Colors.black,
                        padding: const EdgeInsets.symmetric(vertical: 16),
                      ),
                      child: const Text('BACK TO DASHBOARD', style: TextStyle(fontWeight: FontWeight.bold)),
                    ),
                  ),
                ),
              ],
            ),
    );
  }

  Widget _buildActionCard(String title, String description, IconData icon, Color color) {
    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: CIROTheme.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withOpacity(0.3)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color, size: 28),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 14)),
                const SizedBox(height: 4),
                Text(description, style: const TextStyle(color: CIROTheme.textBody, fontSize: 12)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}


