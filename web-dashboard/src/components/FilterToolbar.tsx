/**
 * Reusable Filter Toolbar component.
 */

import React from 'react';
import { Paper, TextField, MenuItem, Button } from '@mui/material';
import ClearIcon from '@mui/icons-material/Clear';

export interface FilterField {
  id: string;
  label: string;
  type?: 'text' | 'select';
  options?: { value: string; label: string }[];
  value: string;
}

interface FilterToolbarProps {
  fields: FilterField[];
  onChange: (id: string, value: string) => void;
  onReset: () => void;
}

export const FilterToolbar: React.FC<FilterToolbarProps> = ({ fields, onChange, onReset }) => {
  const hasActiveFilters = fields.some((f) => f.value !== '');

  return (
    <Paper sx={{ p: 2, mb: 2.5, display: 'flex', flexWrap: 'wrap', gap: 2, alignItems: 'center' }}>
      {fields.map((f) =>
        f.type === 'select' ? (
          <TextField
            key={f.id}
            select
            size="small"
            label={f.label}
            value={f.value}
            onChange={(e) => onChange(f.id, e.target.value)}
            sx={{ minWidth: 160 }}
          >
            <MenuItem value="">
              <em>All</em>
            </MenuItem>
            {f.options?.map((opt) => (
              <MenuItem key={opt.value} value={opt.value}>
                {opt.label}
              </MenuItem>
            ))}
          </TextField>
        ) : (
          <TextField
            key={f.id}
            size="small"
            label={f.label}
            value={f.value}
            onChange={(e) => onChange(f.id, e.target.value)}
            sx={{ minWidth: 160 }}
          />
        )
      )}
      {hasActiveFilters && (
        <Button size="small" variant="outlined" startIcon={<ClearIcon />} onClick={onReset}>
          Clear Filters
        </Button>
      )}
    </Paper>
  );
};
