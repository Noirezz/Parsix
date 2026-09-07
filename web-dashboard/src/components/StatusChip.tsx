/**
 * Reusable Status and Priority Chip with consistent semantic colors.
 */

import React from 'react';
import { Chip, type ChipProps } from '@mui/material';

interface StatusChipProps {
  status: string;
  size?: 'small' | 'medium';
}

export const StatusChip: React.FC<StatusChipProps> = ({ status, size = 'small' }) => {
  const s = status.toUpperCase();

  let color: ChipProps['color'] = 'default';
  let variant: ChipProps['variant'] = 'filled';

  switch (s) {
    case 'ANOMALY':
    case 'HIGH':
    case 'FAILED':
      color = 'error';
      break;
    case 'MEDIUM':
    case 'PENDING':
    case 'WARNING':
      color = 'warning';
      break;
    case 'LOW':
    case 'INFO':
      color = 'info';
      break;
    case 'NORMAL':
    case 'SENT':
    case 'COMPLETED':
    case 'ACTIVE':
    case 'READY':
      color = 'success';
      break;
    default:
      color = 'default';
      variant = 'outlined';
  }

  return <Chip label={status} color={color} variant={variant} size={size} />;
};
