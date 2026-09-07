/**
 * Type-safe API methods for all FastAPI REST endpoints.
 */

import { apiClient } from './client';
import type {
  AggregatedResultResponse,
  AggregateFilterParams,
  AlertFilterParams,
  AlertResponse,
  ChartFilterParams,
  ChartHistoryResponse,
  DetectionFilterParams,
  DetectionResultResponse,
  EventFilterParams,
  HealthResponse,
  MetricsResponse,
  ModuleConfigUpdateRequest,
  ModuleMetadataResponse,
  PaginatedResponse,
  ProcessedEventResponse,
  ReadinessResponse,
} from '../types/api';

export const api = {
  getHealth: () => apiClient<HealthResponse>('/health'),
  getReady: () => apiClient<ReadinessResponse>('/ready'),

  getEvents: (params?: EventFilterParams) =>
    apiClient<PaginatedResponse<ProcessedEventResponse>>('/api/v1/events', {
      params: params as Record<string, string | number | boolean>,
    }),
  getEvent: (eventId: string) => apiClient<ProcessedEventResponse>(`/api/v1/events/${encodeURIComponent(eventId)}`),

  getDetections: (params?: DetectionFilterParams) =>
    apiClient<PaginatedResponse<DetectionResultResponse>>('/api/v1/detections', {
      params: params as Record<string, string | number | boolean>,
    }),
  getDetection: (detectionId: string) =>
    apiClient<DetectionResultResponse>(`/api/v1/detections/${encodeURIComponent(detectionId)}`),

  getAggregates: (params?: AggregateFilterParams) =>
    apiClient<PaginatedResponse<AggregatedResultResponse>>('/api/v1/aggregates', {
      params: params as Record<string, string | number | boolean>,
    }),
  getAggregate: (aggregationId: string) =>
    apiClient<AggregatedResultResponse>(`/api/v1/aggregates/${encodeURIComponent(aggregationId)}`),

  getAlerts: (params?: AlertFilterParams) =>
    apiClient<PaginatedResponse<AlertResponse>>('/api/v1/alerts', {
      params: params as Record<string, string | number | boolean>,
    }),
  getAlert: (alertId: string) => apiClient<AlertResponse>(`/api/v1/alerts/${encodeURIComponent(alertId)}`),

  getModules: () => apiClient<ModuleMetadataResponse[]>('/api/v1/modules'),
  getModule: (moduleId: string) => apiClient<ModuleMetadataResponse>(`/api/v1/modules/${encodeURIComponent(moduleId)}`),
  updateModuleConfig: (moduleId: string, config: ModuleConfigUpdateRequest) =>
    apiClient<ModuleMetadataResponse>(`/api/v1/modules/${encodeURIComponent(moduleId)}/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    }),

  getChartHistory: (params: ChartFilterParams) =>
    apiClient<ChartHistoryResponse>('/api/v1/charts/history', {
      params: params as unknown as Record<string, string | number | boolean>,
    }),

  getMetrics: () => apiClient<MetricsResponse>('/api/v1/metrics'),
};
