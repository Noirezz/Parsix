/**
 * Paginated Detections page with module, status, asset filtering.
 */

import React, { useState } from 'react';
import { Box, Typography } from '@mui/material';
import { usePolling } from '../hooks/usePolling';
import { api } from '../api/endpoints';
import { DataTable, type Column } from '../components/DataTable';
import { FilterToolbar, type FilterField } from '../components/FilterToolbar';
import { StatusChip } from '../components/StatusChip';
import { ErrorBanner } from '../components/ErrorBanner';
import type { DetectionResultResponse } from '../types/api';

export const DetectionsPage: React.FC = () => {
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(50);
  const [moduleId, setModuleId] = useState('');
  const [status, setStatus] = useState('ANOMALY');
  const [asset, setAsset] = useState('');

  const { data, loading, error, refetch } = usePolling({
    fn: () =>
      api.getDetections({
        limit: rowsPerPage,
        offset: page * rowsPerPage,
        module_id: moduleId || undefined,
        status: status || undefined,
        asset: asset || undefined,
      }),
    intervalMs: 6000,
  });

  const filterFields: FilterField[] = [
    {
      id: 'module_id',
      label: 'Module',
      type: 'select',
      value: moduleId,
      options: [
        { value: 'futures-futures-spread', label: 'Futures-Futures Spread' },
        { value: 'spot-futures-spread', label: 'Spot-Futures Spread' },
        { value: 'dex-futures-spread', label: 'DEX-Futures Spread' },
        { value: 'funding-spread', label: 'Funding Spread' },
      ],
    },
    {
      id: 'status',
      label: 'Status',
      type: 'select',
      value: status,
      options: [
        { value: 'ANOMALY', label: 'ANOMALY' },
      ],
    },
    {
      id: 'asset',
      label: 'Asset (e.g. BTC, ETH, SOL)',
      type: 'text',
      value: asset,
    },
  ];

  const handleFilterChange = (id: string, val: string) => {
    setPage(0);
    if (id === 'module_id') setModuleId(val);
    if (id === 'status') setStatus(val);
    if (id === 'asset') setAsset(val);
  };

  const handleFilterReset = () => {
    setPage(0);
    setModuleId('');
    setStatus('');
    setAsset('');
  };

  const columns: Column<DetectionResultResponse>[] = [
    { id: 'result_id', label: 'Result ID', minWidth: 120 },
    {
      id: 'timestamp',
      label: 'Timestamp (UTC)',
      minWidth: 160,
      render: (row) => new Date(row.timestamp).toISOString().replace('T', ' ').substring(0, 19),
    },
    { id: 'asset', label: 'Asset', minWidth: 80 },
    { id: 'module_id', label: 'Module ID', minWidth: 180 },
    {
      id: 'metric_value',
      label: 'Metric Value',
      minWidth: 110,
      align: 'right',
    },
    {
      id: 'threshold',
      label: 'Threshold',
      minWidth: 100,
      align: 'right',
    },
    {
      id: 'anomaly_ratio',
      label: 'Ratio',
      minWidth: 90,
      align: 'right',
    },
    {
      id: 'status',
      label: 'Status',
      minWidth: 100,
      render: (row) => <StatusChip status={row.status} />,
    },
  ];

  return (
    <Box>
      <Box sx={{ mb: 3 }}>
        <Typography variant="h5" sx={{ mb: 0.5 }}>
          Module Detections
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Standardised detection results evaluated by registered deterministic rule modules.
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
        rowKey={(row) => row.result_id}
      />
    </Box>
  );
};
