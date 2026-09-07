/**
 * Backend health/readiness probe badge for the navigation bar.
 */

import React from 'react';
import { Chip, Tooltip } from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import { usePolling } from '../hooks/usePolling';
import { api } from '../api/endpoints';

export const HealthBadge: React.FC = () => {
  const { data: readyData, error: readyError, loading } = usePolling({
    fn: api.getReady,
    intervalMs: 8000,
  });

  const isReady = !readyError && readyData?.status === 'ready';

  if (loading && !readyData && !readyError) {
    return (
      <Tooltip title="Checking backend readiness...">
        <Chip
          icon={<HourglassEmptyIcon style={{ fontSize: 16 }} />}
          label="CHECKING"
          size="small"
          color="default"
          variant="outlined"
        />
      </Tooltip>
    );
  }

  if (isReady) {
    return (
      <Tooltip title="FastAPI and PostgreSQL database connected">
        <Chip
          icon={<CheckCircleIcon style={{ fontSize: 16 }} />}
          label="API READY"
          size="small"
          color="success"
        />
      </Tooltip>
    );
  }

  return (
    <Tooltip title={`Backend unavailable: ${readyError || readyData?.status || 'Disconnected'}`}>
      <Chip
        icon={<ErrorOutlineIcon style={{ fontSize: 16 }} />}
        label="API DEGRADED"
        size="small"
        color="error"
      />
    </Tooltip>
  );
};
