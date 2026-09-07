/**
 * Overview dashboard page summarizing health, KPI counters, recent detections and alerts.
 */

import React from 'react';
import { Box, Typography, Grid, Paper, Divider } from '@mui/material';
import DynamicFeedIcon from '@mui/icons-material/DynamicFeed';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import LayersIcon from '@mui/icons-material/Layers';
import NotificationsActiveIcon from '@mui/icons-material/NotificationsActive';
import { usePolling } from '../hooks/usePolling';
import { api } from '../api/endpoints';
import { MetricCard } from '../components/MetricCard';
import { StatusChip } from '../components/StatusChip';
import { ErrorBanner } from '../components/ErrorBanner';

export const OverviewPage: React.FC = () => {
  const { data: metrics, error: metricsError, loading: metricsLoading, refetch } = usePolling({
    fn: api.getMetrics,
    intervalMs: 5000,
  });

  const { data: recentAlerts, loading: alertsLoading } = usePolling({
    fn: () => api.getAlerts({ limit: 5 }),
    intervalMs: 5000,
  });

  const { data: recentDetections, loading: detectionsLoading } = usePolling({
    fn: () => api.getDetections({ limit: 5, status: 'ANOMALY' }),
    intervalMs: 5000,
  });

  return (
    <Box>
      <Box sx={{ mb: 3 }}>
        <Typography variant="h5" sx={{ mb: 0.5 }}>
          System Overview
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Real-time telemetry and anomaly detection summary across cryptocurrency infrastructure.
        </Typography>
      </Box>

      {metricsError && <ErrorBanner message={metricsError} onRetry={refetch} />}

      <Grid container spacing={2.5} sx={{ mb: 4 }}>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="Processed Events"
            value={metrics?.total_processed_events}
            subtitle="Idempotency layer throughput"
            icon={<DynamicFeedIcon fontSize="large" />}
            loading={metricsLoading}
            color="#3B82F6"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="Anomalies Detected"
            value={metrics?.detections_by_status?.ANOMALY ?? metrics?.total_detections}
            subtitle="Verified threshold breaches"
            icon={<WarningAmberIcon fontSize="large" />}
            loading={metricsLoading}
            color="#F59E0B"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="Aggregated Candidates"
            value={metrics?.total_aggregates}
            subtitle="Correlated anomaly groups"
            icon={<LayersIcon fontSize="large" />}
            loading={metricsLoading}
            color="#8B5CF6"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="Generated Alerts"
            value={metrics?.total_alerts}
            subtitle={`${metrics?.alerts_by_priority?.HIGH || 0} High Priority`}
            icon={<NotificationsActiveIcon fontSize="large" />}
            loading={metricsLoading}
            color="#EF4444"
          />
        </Grid>
      </Grid>

      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2.5, height: '100%' }}>
            <Typography variant="h6" sx={{ mb: 2 }}>
              Recent Alerts
            </Typography>
            <Divider sx={{ mb: 2 }} />
            {alertsLoading && !recentAlerts ? (
              <Typography color="text.secondary">Loading alerts...</Typography>
            ) : (recentAlerts?.items?.length || 0) === 0 ? (
              <Typography color="text.secondary">No alerts recorded yet.</Typography>
            ) : (
              recentAlerts?.items.map((alert) => (
                <Box
                  key={alert.alert_id}
                  sx={{
                    p: 1.5,
                    mb: 1.5,
                    backgroundColor: '#161F30',
                    borderRadius: 1.5,
                    border: '1px solid #1F2937',
                  }}
                >
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.5 }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                      {alert.title}
                    </Typography>
                    <StatusChip status={alert.priority} />
                  </Box>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                    {alert.summary}
                  </Typography>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
                      Asset: {alert.asset} | Score: {alert.anomaly_score}
                    </Typography>
                    <StatusChip status={alert.notification_status} size="small" />
                  </Box>
                </Box>
              ))
            )}
          </Paper>
        </Grid>

        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2.5, height: '100%' }}>
            <Typography variant="h6" sx={{ mb: 2 }}>
              Recent Detection Results
            </Typography>
            <Divider sx={{ mb: 2 }} />
            {detectionsLoading && !recentDetections ? (
              <Typography color="text.secondary">Loading detections...</Typography>
            ) : (recentDetections?.items?.length || 0) === 0 ? (
              <Typography color="text.secondary">No detections recorded yet.</Typography>
            ) : (
              recentDetections?.items.map((det) => (
                <Box
                  key={det.result_id}
                  sx={{
                    p: 1.5,
                    mb: 1.5,
                    backgroundColor: '#161F30',
                    borderRadius: 1.5,
                    border: '1px solid #1F2937',
                  }}
                >
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.5 }}>
                    <Typography variant="subtitle2" sx={{ fontFamily: 'monospace' }}>
                      {det.module_id} ({det.asset})
                    </Typography>
                    <StatusChip status={det.status} />
                  </Box>
                  <Typography variant="caption" color="text.secondary" display="block">
                    Metric: {det.metric_value} | Threshold: {det.threshold} | Ratio: {det.anomaly_ratio}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    Timestamp: {new Date(det.timestamp).toLocaleString()}
                  </Typography>
                </Box>
              ))
            )}
          </Paper>
        </Grid>
      </Grid>
    </Box>
  );
};
