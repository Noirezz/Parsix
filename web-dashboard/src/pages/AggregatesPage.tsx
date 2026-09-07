/**
 * Paginated Aggregated Anomaly Results page with priority and asset filtering.
 */

import React, { useState } from 'react';
import { Box, Typography } from '@mui/material';
import { usePolling } from '../hooks/usePolling';
import { api } from '../api/endpoints';
import { DataTable, type Column } from '../components/DataTable';
import { FilterToolbar, type FilterField } from '../components/FilterToolbar';
import { StatusChip } from '../components/StatusChip';
import { ErrorBanner } from '../components/ErrorBanner';
import type { AggregatedResultResponse } from '../types/api';

export const AggregatesPage: React.FC = () => {
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(50);
  const [priority, setPriority] = useState('');
  const [asset, setAsset] = useState('');

  const { data, loading, error, refetch } = usePolling({
    fn: () =>
      api.getAggregates({
        limit: rowsPerPage,
        offset: page * rowsPerPage,
        priority: priority || undefined,
        asset: asset || undefined,
      }),
    intervalMs: 6000,
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
      id: 'asset',
      label: 'Asset',
      type: 'text',
      value: asset,
    },
  ];

  const handleFilterChange = (id: string, val: string) => {
    setPage(0);
    if (id === 'priority') setPriority(val);
    if (id === 'asset') setAsset(val);
  };

  const handleFilterReset = () => {
    setPage(0);
    setPriority('');
    setAsset('');
  };

  const columns: Column<AggregatedResultResponse>[] = [
    { id: 'aggregation_id', label: 'Aggregation ID', minWidth: 120 },
    {
      id: 'timestamp',
      label: 'Timestamp (UTC)',
      minWidth: 160,
      render: (row) => new Date(row.timestamp).toISOString().replace('T', ' ').substring(0, 19),
    },
    { id: 'asset', label: 'Asset', minWidth: 80 },
    {
      id: 'composite_anomaly_score',
      label: 'Composite Score',
      minWidth: 120,
      align: 'right',
    },
    {
      id: 'max_anomaly_ratio',
      label: 'Max Ratio',
      minWidth: 100,
      align: 'right',
    },
    {
      id: 'module_count',
      label: 'Modules',
      minWidth: 90,
      align: 'center',
    },
    {
      id: 'triggered_modules',
      label: 'Triggered Modules',
      minWidth: 180,
      render: (row) => row.triggered_modules.join(', '),
    },
    {
      id: 'priority',
      label: 'Priority',
      minWidth: 100,
      render: (row) => <StatusChip status={row.priority} />,
    },
  ];

  return (
    <Box>
      <Box sx={{ mb: 3 }}>
        <Typography variant="h5" sx={{ mb: 0.5 }}>
          Aggregated Anomaly Results
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Combined multi-module signals correlated across time windows for prioritized anomaly evaluation.
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
        rowKey={(row) => row.aggregation_id}
      />
    </Box>
  );
};
