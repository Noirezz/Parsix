/**
 * Paginated Alerts page with priority and notification delivery status filtering.
 */

import React, { useState } from 'react';
import { Box, Typography } from '@mui/material';
import { usePolling } from '../hooks/usePolling';
import { api } from '../api/endpoints';
import { DataTable, type Column } from '../components/DataTable';
import { FilterToolbar, type FilterField } from '../components/FilterToolbar';
import { StatusChip } from '../components/StatusChip';
import { ErrorBanner } from '../components/ErrorBanner';
import type { AlertResponse } from '../types/api';

export const AlertsPage: React.FC = () => {
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(50);
  const [priority, setPriority] = useState('');
  const [notificationStatus, setNotificationStatus] = useState('');
  const [asset, setAsset] = useState('');

  const { data, loading, error, refetch } = usePolling({
    fn: () =>
      api.getAlerts({
        limit: rowsPerPage,
        offset: page * rowsPerPage,
        priority: priority || undefined,
        notification_status: notificationStatus || undefined,
        asset: asset || undefined,
      }),
    intervalMs: 5000,
  });

  const filterFields: FilterField[] = [
    {
      id: 'priority',
      label: 'Priority',
      type: 'select',
      value: priority,
      options: [
        { value: 'HIGH', label: 'HIGH' },
        { value: 'MEDIUM', label: 'MEDIUM' },
        { value: 'LOW', label: 'LOW' },
      ],
    },
    {
      id: 'notification_status',
      label: 'Delivery Status',
      type: 'select',
      value: notificationStatus,
      options: [
        { value: 'SENT', label: 'SENT' },
        { value: 'PENDING', label: 'PENDING' },
        { value: 'FAILED', label: 'FAILED' },
      ],
    },
    {
      id: 'asset',
      label: 'Asset',
      type: 'text',
      value: asset,
    },
  ];

  const handleFilterChange = (id: string, val: string) => {
    setPage(0);
    if (id === 'priority') setPriority(val);
    if (id === 'notification_status') setNotificationStatus(val);
    if (id === 'asset') setAsset(val);
  };

  const handleFilterReset = () => {
    setPage(0);
    setPriority('');
    setNotificationStatus('');
    setAsset('');
  };

  const columns: Column<AlertResponse>[] = [
    { id: 'alert_id', label: 'Alert ID', minWidth: 110 },
    {
      id: 'timestamp',
      label: 'Timestamp (UTC)',
      minWidth: 150,
      render: (row) => new Date(row.timestamp).toISOString().replace('T', ' ').substring(0, 19),
    },
    { id: 'asset', label: 'Asset', minWidth: 70 },
    {
      id: 'priority',
      label: 'Priority',
      minWidth: 90,
      render: (row) => <StatusChip status={row.priority} />,
    },
    { id: 'title', label: 'Title', minWidth: 180 },
    { id: 'summary', label: 'Summary', minWidth: 240 },
    {
      id: 'notification_status',
      label: 'Delivery',
      minWidth: 100,
      render: (row) => <StatusChip status={row.notification_status} />,
    },
    {
      id: 'notification_attempts',
      label: 'Attempts',
      minWidth: 80,
      align: 'center',
    },
  ];

  return (
    <Box>
      <Box sx={{ mb: 3 }}>
        <Typography variant="h5" sx={{ mb: 0.5 }}>
          Generated Alerts
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Prioritised notification-ready alerts dispatched to the Telegram bot channel.
        </Typography>
      </Box>

      <FilterToolbar fields={filterFields} onChange={handleFilterChange} onReset={handleFilterReset} />

      {error && <ErrorBanner message={error} onRetry={refetch} />}

      <DataTable
        columns={columns}
        rows={data?.items || []}
        total={data?.total || 0}
        page={page}
        rowsPerPage={rowsPerPage}
        loading={loading}
        onPageChange={setPage}
        onRowsPerPageChange={(r) => {
          setRowsPerPage(r);
          setPage(0);
        }}
        rowKey={(row) => row.alert_id}
      />
    </Box>
  );
};
