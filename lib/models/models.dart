import 'dart:convert';

class DatasetResponse {
  final Map<String, dynamic> datasets;
  final String version;

  DatasetResponse({required this.datasets, required this.version});

  factory DatasetResponse.fromJson(Map<String, dynamic> json) {
    return DatasetResponse(
      version: json['ciro_datasets']['version'] ?? '1.0.0',
      datasets: json['ciro_datasets'],
    );
  }
}

class SocialMediaPost {
  final String postId;
  final String scenarioId;
  final String timestamp;
  final String platform;
  final String language;
  final String user;
  final String userType;
  final String text;
  final String? locationMentioned;
  final String? locationTag;
  final String city;
  final String crisisTypeHint;
  final String sentiment;
  final bool crisisSignal;
  final List<String> keywords;
  final String phase;

  SocialMediaPost({
    required this.postId,
    required this.scenarioId,
    required this.timestamp,
    required this.platform,
    required this.language,
    required this.user,
    required this.userType,
    required this.text,
    this.locationMentioned,
    this.locationTag,
    required this.city,
    required this.crisisTypeHint,
    required this.sentiment,
    required this.crisisSignal,
    required this.keywords,
    required this.phase,
  });

  factory SocialMediaPost.fromJson(Map<String, dynamic> json) {
    return SocialMediaPost(
      postId: json['post_id'],
      scenarioId: json['scenario_id'],
      timestamp: json['timestamp'],
      platform: json['platform'],
      language: json['language'],
      user: json['user'],
      userType: json['user_type'],
      text: json['text'],
      locationMentioned: json['location_mentioned'],
      locationTag: json['location_tag'],
      city: json['city'],
      crisisTypeHint: json['crisis_type_hint'],
      sentiment: json['sentiment'],
      crisisSignal: json['crisis_signal'] ?? false,
      keywords: List<String>.from(json['keywords_extracted'] ?? []),
      phase: json['phase'],
    );
  }
}

class WeatherSnapshot {
  final String snapshotId;
  final String scenarioId;
  final String phase;
  final String timestamp;
  final double temperatureC;
  final double humidity;
  final double rainfallMmHr;
  final String alertLevel;
  final String alertType;

  WeatherSnapshot({
    required this.snapshotId,
    required this.scenarioId,
    required this.phase,
    required this.timestamp,
    required this.temperatureC,
    required this.humidity,
    required this.rainfallMmHr,
    required this.alertLevel,
    required this.alertType,
  });

  factory WeatherSnapshot.fromJson(Map<String, dynamic> json) {
    return WeatherSnapshot(
      snapshotId: json['snapshot_id'],
      scenarioId: json['scenario_id'],
      phase: json['phase'],
      timestamp: json['timestamp'],
      temperatureC: (json['temperature_c'] as num).toDouble(),
      humidity: (json['humidity_percent'] as num).toDouble(),
      rainfallMmHr: (json['rainfall_mm_per_hour'] as num).toDouble(),
      alertLevel: json['alert_level'] ?? 'NONE',
      alertType: json['alert_type'] ?? 'CLEAR',
    );
  }
}

class ResponseAction {
  final String actionId;
  final String scenarioId;
  final String actionType;
  final String actionName;
  final String description;
  final int priority;
  final String targetZone;
  final String resourceUsedName;
  final String agentTraceNote;
  final String status;

  ResponseAction({
    required this.actionId,
    required this.scenarioId,
    required this.actionType,
    required this.actionName,
    required this.description,
    required this.priority,
    required this.targetZone,
    required this.resourceUsedName,
    required this.agentTraceNote,
    required this.status,
  });

  factory ResponseAction.fromJson(Map<String, dynamic> json) {
    return ResponseAction(
      actionId: json['action_id'],
      scenarioId: json['scenario_id'],
      actionType: json['action_type'],
      actionName: json['action_name'],
      description: json['description'],
      priority: json['priority'],
      targetZone: json['target_zone'],
      resourceUsedName: json['resource_used_name'],
      agentTraceNote: json['agent_trace_note'],
      status: json['simulation_status'],
    );
  }
}

class EmergencyResource {
  final String resourceId;
  final String type;
  final String name;
  final String city;
  final double lat;
  final double lng;
  final String status;

  EmergencyResource({
    required this.resourceId,
    required this.type,
    required this.name,
    required this.city,
    required this.lat,
    required this.lng,
    required this.status,
  });

  factory EmergencyResource.fromJson(Map<String, dynamic> json) {
    return EmergencyResource(
      resourceId: json['resource_id'],
      type: json['resource_type'],
      name: json['name'],
      city: json['city'],
      lat: (json['lat'] as num).toDouble(),
      lng: (json['lng'] as num).toDouble(),
      status: json['status'],
    );
  }
}

class TrafficRoad {
  final String roadId;
  final String roadName;
  final String city;
  final String zone;
  final String scenarioId;
  final double latStart;
  final double lngStart;
  final double latEnd;
  final double lngEnd;
  final dynamic T0;
  final dynamic T1;
  final dynamic T2;

  TrafficRoad({
    required this.roadId,
    required this.roadName,
    required this.city,
    required this.zone,
    required this.scenarioId,
    required this.latStart,
    required this.lngStart,
    required this.latEnd,
    required this.lngEnd,
    this.T0,
    this.T1,
    this.T2,
  });

  factory TrafficRoad.fromJson(Map<String, dynamic> json) {
    return TrafficRoad(
      roadId: json['road_id'],
      roadName: json['road_name'],
      city: json['city'],
      zone: json['zone'],
      scenarioId: json['scenario_id'],
      latStart: (json['lat_start'] as num).toDouble(),
      lngStart: (json['lng_start'] as num).toDouble(),
      latEnd: (json['lat_end'] as num).toDouble(),
      lngEnd: (json['lng_end'] as num).toDouble(),
      T0: json['T0'],
      T1: json['T1'],
      T2: json['T2'],
    );
  }
}
