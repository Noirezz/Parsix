/**
 * Summary KPI Metric Card component.
 */

import React from 'react';
import { Card, CardContent, Typography, Box, Skeleton } from '@mui/material';

interface MetricCardProps {
  title: string;
  value: number | string | null | undefined;
  subtitle?: string;
  icon: React.ReactNode;
  loading?: boolean;
  color?: string;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  title,
  value,
  subtitle,
  icon,
  loading = false,
  color = '#3B82F6',
}) => {
  return (
    <Card sx={{ height: '100%', position: 'relative', overflow: 'hidden' }}>
      <Box
        sx={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: 3,
          backgroundColor: color,
        }}
      />
      <CardContent sx={{ p: 2.5 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1 }}>
          <Typography variant="subtitle2" color="text.secondary">
            {title}
          </Typography>
          <Box sx={{ color, opacity: 0.9 }}>{icon}</Box>
        </Box>
        {loading ? (
          <Skeleton variant="text" width="60%" height={40} />
        ) : (
          <Typography variant="h4" sx={{ fontWeight: 700, fontFamily: 'monospace', mb: 0.5 }}>
            {value !== undefined && value !== null ? value : '-'}
          </Typography>
        )}
        {subtitle && (
          <Typography variant="caption" color="text.secondary">
            {subtitle}
          </Typography>
        )}
      </CardContent>
    </Card>
  );
};
