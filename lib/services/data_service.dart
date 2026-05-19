import 'package:intl/intl.dart';
import 'dart:convert';
import 'package:flutter/services.dart';
import 'package:ciro/models/models.dart';

class DataService {
  static final DataService _instance = DataService._internal();
  factory DataService() => _instance;
  DataService._internal();

  Map<String, dynamic>? _rawDatasets;
  bool _isLoaded = false;

  Future<void> loadDatasets() async {
    if (_isLoaded) return;
    
    try {
      final String jsonString = await rootBundle.loadString('ciro_datasets.json');
      final Map<String, dynamic> jsonResponse = json.decode(jsonString);
      _rawDatasets = jsonResponse['ciro_datasets'];
      _isLoaded = true;
    } catch (e) {
      print('Error loading datasets: $e');
    }
  }

  List<SocialMediaPost> getPosts(String scenarioId, {String? phase}) {
    if (!_isLoaded) return [];
    
    final postsData = _rawDatasets?['DS-001']?['posts'];
    if (postsData == null) return [];

    List<SocialMediaPost> allPosts = [];
    
    // JSON has phases as keys: T0_before, T1_during, T2_after_response
    if (phase != null) {
      final phasePosts = postsData[phase] as List?;
      if (phasePosts != null) {
        allPosts.addAll(phasePosts.map((p) => SocialMediaPost.fromJson(p)));
      }
    } else {
      postsData.forEach((key, value) {
        final phasePosts = value as List;
        allPosts.addAll(phasePosts.map((p) => SocialMediaPost.fromJson(p)));
      });
    }

    return allPosts.where((p) => p.scenarioId == scenarioId).toList();
  }

  List<WeatherSnapshot> getWeatherSnapshots(String scenarioId) {
    if (!_isLoaded) return [];
    
    final snapshotsData = _rawDatasets?['DS-002']?['snapshots']?[scenarioId];
    if (snapshotsData == null) return [];

    List<WeatherSnapshot> snapshots = [];
    snapshotsData.forEach((phase, data) {
      snapshots.add(WeatherSnapshot.fromJson(data));
    });
    return snapshots;
  }

  List<TrafficRoad> getRoads(String scenarioId) {
    if (!_isLoaded) return [];
    
    final roadsData = _rawDatasets?['DS-003']?['roads'] as List?;
    if (roadsData == null) return [];

    return roadsData
        .map((r) => TrafficRoad.fromJson(r))
        .where((r) => r.scenarioId == scenarioId)
        .toList();
  }

  List<EmergencyResource> getResources({String? city, String? scenarioId}) {
    if (!_isLoaded) return [];
    
    final resourcesData = _rawDatasets?['DS-004']?['resources'] as List?;
    if (resourcesData == null) return [];

    var resources = resourcesData.map((r) => EmergencyResource.fromJson(r));
    
    if (city != null) {
      resources = resources.where((r) => r.city == city);
    }
    
    // Note: DS-004 doesn't strictly have scenarioId on all resources, 
    // but some have scenario_assigned.
    return resources.toList();
  }

  List<ResponseAction> getActions(String scenarioId) {
    if (!_isLoaded) return [];
    
    final actionsData = _rawDatasets?['DS-006']?['actions'] as List?;
    if (actionsData == null) return [];

    return actionsData
        .map((a) => ResponseAction.fromJson(a))
        .where((a) => a.scenarioId == scenarioId)
        .toList()
      ..sort((a, b) => a.priority.compareTo(b.priority));
  }

  Map<String, dynamic>? getZoneInfo(String zoneName) {
    if (!_isLoaded) return null;
    
    final zonesData = _rawDatasets?['DS-005']?['zones'] as List?;
    if (zonesData == null) return null;

    return zonesData.firstWhere(
      (z) => z['zone_name'] == zoneName || (z['zone_alias'] as List).contains(zoneName),
      orElse: () => null,
    );
  }
  
  String getScenarioId(String scenarioName) {
    switch (scenarioName) {
      case 'Urban Flooding': return 'SCN-001';
      case 'Heatwave Emergency': return 'SCN-002';
      case 'Road Blockage': return 'SCN-003';
      case 'Road Accident': return 'SCN-004';
      case 'Infrastructure Failure': return 'SCN-005';
      default: return 'SCN-001';
    }
  }

  Map<String, String>? getScenarioMetrics(String scenarioName) {
    if (!_isLoaded) return null;
    final scenarioId = getScenarioId(scenarioName);
    
    // Attempt to find a historical event similar to this scenario for realistic metrics
    final historicalData = _rawDatasets?['DS-008']?['events'] as List?;
    final similarEvent = historicalData?.firstWhere(
      (e) => e['similar_to_scenario_id'] == scenarioId,
      orElse: () => null,
    );

    if (similarEvent != null) {
      return {
        'congestion_reduction': '${similarEvent['congestion_reduction_achieved'] ?? 65}%',
        'response_time': '${similarEvent['response_time_mins']} min',
        'citizens_notified': NumberFormat('#,###').format(similarEvent['alerts_sent'] ?? 1200),
      };
    }

    // Fallback metrics
    return {
      'congestion_reduction': '74%',
      'response_time': '18 min',
      'citizens_notified': '1,247',
    };
  }
}
