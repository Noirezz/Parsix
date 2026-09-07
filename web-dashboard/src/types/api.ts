/**
 * TypeScript definitions mapped 1-to-1 from the FastAPI OpenAPI schema.
 */

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface HealthResponse {
  status: string;
  service: string;
}

export interface ReadinessResponse {
  status: string;
  database: string;
}

export interface ProcessedEventResponse {
  event_id: string;
  status: string;
  processed_at: string;
}

export interface DetectionResultResponse {
  result_id: string;
  event_id: string;
  module_id: string;
  timestamp: string;
  asset: string;
  metric_value: string;
  threshold: string;
  anomaly_ratio: string;
  status: string;
  persistence: number;
  metadata: Record<string, unknown>;
}

export interface AggregatedResultResponse {
  aggregation_id: string;
  timestamp: string;
  asset: string;
  composite_anomaly_score: string;
  max_anomaly_ratio: string;
  average_anomaly_ratio: string;
  priority: string;
  module_count: number;
  triggered_modules: string[];
  correlation_window: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export interface AlertResponse {
  alert_id: string;
  event_id: string | null;
  timestamp: string;
  asset: string;
  priority: string;
  title: string;
  summary: string;
  anomaly_score: string;
  triggered_modules: string[];
  details: Record<string, unknown>;
  notification_status: string;
  notification_attempts: number;
  notified_at: string | null;
  last_notification_error: string | null;
  created_at: string;
}

export interface ModuleMetadataResponse {
  module_id: string;
  status: string;
  description: string;
  threshold: string;
  reference_price_mode: string;
  max_price_ratio: string;
  updated_at: string | null;
}

export interface ModuleConfigUpdateRequest {
  threshold?: number | string;
  status?: string;
  reference_price_mode?: string;
  max_price_ratio?: number | string;
}

export interface MetricsResponse {
  total_processed_events: number;
  total_detections: number;
  detections_by_status: Record<string, number>;
  detections_by_module: Record<string, number>;
  total_aggregates: number;
  total_alerts: number;
  alerts_by_priority: Record<string, number>;
  alerts_by_notification_status: Record<string, number>;
}

export interface EventFilterParams {
  limit?: number;
  offset?: number;
  event_id?: string;
  status?: string;
  from_timestamp?: string;
  to_timestamp?: string;
}

export interface DetectionFilterParams {
  limit?: number;
  offset?: number;
  event_id?: string;
  module_id?: string;
  status?: string;
  asset?: string;
  from_timestamp?: string;
  to_timestamp?: string;
}

export interface AggregateFilterParams {
  limit?: number;
  offset?: number;
  asset?: string;
  priority?: string;
  from_timestamp?: string;
  to_timestamp?: string;
}

export interface AlertFilterParams {
  limit?: number;
  offset?: number;
  event_id?: string;
  priority?: string;
  notification_status?: string;
  asset?: string;
  from_timestamp?: string;
  to_timestamp?: string;
}

export interface ChartPoint {
  timestamp: string;
  time_epoch: number;
  price_1: number | string | null;
  source_1: string | null;
  price_2: number | string | null;
  source_2: string | null;
  spread_percent: number | string;
  threshold: number | string;
  is_anomaly: boolean;
}

export interface ChartHistoryResponse {
  asset: string;
  symbol: string;
  module_id: string;
  timeframe: string;
  points: ChartPoint[];
  current_spread: number | string | null;
  max_spread: number | string | null;
  avg_spread: number | string | null;
  spread_duration_seconds: number | null;
}

export interface ChartFilterParams {
  asset: string;
  symbol?: string;
  module_id?: string;
  timeframe?: string;
}
