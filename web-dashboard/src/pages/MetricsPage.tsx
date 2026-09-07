/**
 * Operational Metrics & Analytics breakdown page.
 */

import React from 'react';
import { Box, Typography, Grid, Paper, Divider, Table, TableBody, TableCell, TableHead, TableRow } from '@mui/material';
import { usePolling } from '../hooks/usePolling';
import { api } from '../api/endpoints';
import { MetricCard } from '../components/MetricCard';
import { StatusChip } from '../components/StatusChip';
import { ErrorBanner } from '../components/ErrorBanner';
import AssessmentIcon from '@mui/icons-material/Assessment';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import PriorityHighIcon from '@mui/icons-material/PriorityHigh';
import SendIcon from '@mui/icons-material/Send';

export const MetricsPage: React.FC = () => {
  const { data: metrics, loading, error, refetch } = usePolling({
    fn: api.getMetrics,
    intervalMs: 5000,
  });

  return (
    <Box>
      <Box sx={{ mb: 3 }}>
        <Typography variant="h5" sx={{ mb: 0.5 }}>
          Operational Metrics
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Database-derived persistence counters, status distributions, and module activity.
        </Typography>
      </Box>

      {error && <ErrorBanner message={error} onRetry={refetch} />}

      <Grid container spacing={2.5} sx={{ mb: 4 }}>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="Total Events"
            value={metrics?.total_processed_events}
            subtitle="Processed records"
            icon={<AssessmentIcon fontSize="large" />}
            loading={loading}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="Total Detections"
            value={metrics?.total_detections}
            subtitle="Module evaluations"
            icon={<CheckCircleIcon fontSize="large" />}
            loading={loading}
            color="#10B981"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="Total Alerts"
            value={metrics?.total_alerts}
            subtitle="Prioritised anomalies"
            icon={<PriorityHighIcon fontSize="large" />}
            loading={loading}
            color="#EF4444"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="Sent Notifications"
            value={metrics?.alerts_by_notification_status?.SENT || 0}
            subtitle="Telegram deliveries"
            icon={<SendIcon fontSize="large" />}
            loading={loading}
            color="#8B5CF6"
          />
        </Grid>
      </Grid>

      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2.5 }}>
            <Typography variant="h6" sx={{ mb: 2 }}>
              Detections by Module
            </Typography>
            <Divider sx={{ mb: 2 }} />
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Module Identifier</TableCell>
                  <TableCell align="right">Detections</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {Object.entries(metrics?.detections_by_module || {}).map(([modId, count]) => (
                  <TableRow key={modId}>
                    <TableCell sx={{ fontFamily: 'monospace' }}>{modId}</TableCell>
                    <TableCell align="right" sx={{ fontWeight: 600 }}>
                      {count}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Paper>
        </Grid>

        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2.5 }}>
            <Typography variant="h6" sx={{ mb: 2 }}>
              Alerts by Priority & Delivery Status
            </Typography>
            <Divider sx={{ mb: 2 }} />
            <Typography variant="subtitle2" sx={{ mb: 1, color: 'text.secondary' }}>
              Priority Distribution
            </Typography>
            <Table size="small" sx={{ mb: 3 }}>
              <TableBody>
                {Object.entries(metrics?.alerts_by_priority || {}).map(([pri, count]) => (
                  <TableRow key={pri}>
                    <TableCell>
                      <StatusChip status={pri} />
                    </TableCell>
                    <TableCell align="right" sx={{ fontWeight: 600 }}>
                      {count}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>

            <Typography variant="subtitle2" sx={{ mb: 1, color: 'text.secondary' }}>
              Notification Delivery Status
            </Typography>
            <Table size="small">
              <TableBody>
                {Object.entries(metrics?.alerts_by_notification_status || {}).map(([st, count]) => (
                  <TableRow key={st}>
                    <TableCell>
                      <StatusChip status={st} />
                    </TableCell>
                    <TableCell align="right" sx={{ fontWeight: 600 }}>
                      {count}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Paper>
        </Grid>
      </Grid>
    </Box>
  );
};
