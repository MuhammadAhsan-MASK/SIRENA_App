import 'package:flutter/material.dart';
import 'package:ciro/theme/app_theme.dart';
import 'package:ciro/services/data_service.dart';
import 'package:ciro/models/models.dart';
import 'package:intl/intl.dart';

class SignalFeedList extends StatelessWidget {
  final String scenario;
  final String? activeOrigin;
  final String? activeDestination;

  const SignalFeedList({
    super.key, 
    required this.scenario,
    this.activeOrigin,
    this.activeDestination,
  });

  String _formatTimeString(String isoTime) {
    try {
      final dateTime = DateTime.parse(isoTime);
      final now = DateTime(2025, 5, 15, 14, 30); // Mock current time for realism
      final diff = now.difference(dateTime);
      if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
      if (diff.inHours < 24) return '${diff.inHours}h ago';
      return DateFormat('HH:mm').format(dateTime);
    } catch (e) {
      return 'Just now';
    }
  }

  @override
  Widget build(BuildContext context) {
    final scenarioId = DataService().getScenarioId(scenario);
    final data = DataService();
    
    // 1. Determine base city from scenario
    String visualCity = ['SCN-001', 'SCN-003', 'SCN-004'].contains(scenarioId) ? 'Islamabad' : 'Karachi';
    
    // 2. If signal is present, we might be switching cities!
    Map<String, dynamic>? activeZone;
    if (activeOrigin != null) {
      activeZone = data.getZoneInfo(activeOrigin!);
    } else if (activeDestination != null) {
      activeZone = data.getZoneInfo(activeDestination!);
    }

    if (activeZone != null && activeZone['city'] != null) {
      visualCity = activeZone['city']!;
    }

    // Fetch posts for T1_during phase (active crisis)
    final allPosts = data.getPosts(scenarioId, phase: 'T1_during');
    
    // 3. Filter by city!
    final posts = allPosts.where((p) => p.city == visualCity).toList();

    if (posts.isEmpty) {
      return const Center(
        child: Text(
          'NO SIGNALS DETECTED',
          style: TextStyle(color: CIROTheme.textDim, fontSize: 10, letterSpacing: 1.5),
        ),
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.all(12),
      itemCount: posts.length,
      itemBuilder: (context, index) {
        final post = posts[index];
        return InkWell(
          onTap: () => _showSignalDetail(context, post),
          child: Container(
            margin: const EdgeInsets.only(bottom: 12),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.white.withOpacity(0.03),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: Colors.white10),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Flexible(
                      child: Text(
                        post.platform.toUpperCase(),
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          color: post.crisisSignal ? CIROTheme.secondary : CIROTheme.primary,
                          fontSize: 9,
                          fontWeight: FontWeight.bold,
                          letterSpacing: 1.0,
                        ),
                      ),
                    ),
                    Flexible(
                      child: Text(
                        _formatTimeString(post.timestamp),
                        style: const TextStyle(color: CIROTheme.textDim, fontSize: 9),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Text(
                  post.text,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 12, color: CIROTheme.textBody),
                ),
                if (post.locationMentioned != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 8.0),
                    child: Row(
                      children: [
                        const Icon(Icons.location_on, color: CIROTheme.textDim, size: 10),
                        const SizedBox(width: 4),
                        Expanded(
                          child: Text(
                            post.locationMentioned!,
                            style: const TextStyle(color: CIROTheme.textDim, fontSize: 9),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }

  void _showSignalDetail(BuildContext context, SocialMediaPost post) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: CIROTheme.surface,
        title: Row(
          children: [
            Icon(Icons.radar, color: post.crisisSignal ? CIROTheme.secondary : CIROTheme.primary, size: 20),
            const SizedBox(width: 12),
            const Text('SIGNAL DETAILS', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, letterSpacing: 1.5)),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _buildDetailRow('SOURCE', post.platform),
            _buildDetailRow('USER', post.user),
            _buildDetailRow('LANGUAGE', post.language),
            _buildDetailRow('PHASE', post.phase),
            _buildDetailRow('STATUS', post.crisisSignal ? 'CRISIS SIGNAL' : 'NOISE'),
            const Divider(color: Colors.white10),
            const SizedBox(height: 8),
            Text(
              post.text,
              style: const TextStyle(fontSize: 14, color: Colors.white, height: 1.5),
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: post.keywords.map((k) => Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: CIROTheme.primary.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(4),
                  border: Border.all(color: CIROTheme.primary.withOpacity(0.3)),
                ),
                child: Text(k, style: const TextStyle(fontSize: 9, color: CIROTheme.primary)),
              )).toList(),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('DISMISS', style: TextStyle(color: CIROTheme.primary)),
          ),
        ],
      ),
    );
  }

  Widget _buildDetailRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8.0),
      child: Row(
        children: [
          Text('$label: ', style: const TextStyle(color: CIROTheme.textDim, fontSize: 10, fontWeight: FontWeight.bold)),
          Expanded(
            child: Text(
              value, 
              style: const TextStyle(color: CIROTheme.primary, fontSize: 10),
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }
}
