/**
 * Detection Module Management & Dynamic Threshold Settings page.
 */

import React, { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  Grid,
  Card,
  CardContent,
  Chip,
  Skeleton,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Switch,
  FormControlLabel,
  Button,
  Alert,
  Snackbar,
  CircularProgress,
  Divider,
  InputAdornment,
} from '@mui/material';
import ExtensionIcon from '@mui/icons-material/Extension';
import SaveIcon from '@mui/icons-material/Save';
import RefreshIcon from '@mui/icons-material/Refresh';
import TuneIcon from '@mui/icons-material/Tune';
import ShowChartIcon from '@mui/icons-material/ShowChart';
import CurrencyExchangeIcon from '@mui/icons-material/CurrencyExchange';
import SwapHorizIcon from '@mui/icons-material/SwapHoriz';
import HubIcon from '@mui/icons-material/Hub';

import { usePolling } from '../hooks/usePolling';
import { api } from '../api/endpoints';
import { ErrorBanner } from '../components/ErrorBanner';
import type { ModuleConfigUpdateRequest } from '../types/api';

const MODULE_TITLES: Record<string, { title: string; icon: React.ReactElement; color: string }> = {
  'futures-futures-spread': {
    title: 'Futures-Futures Spread Module',
    icon: <SwapHorizIcon sx={{ color: '#60A5FA' }} />,
    color: '#1E3A8A',
  },
  'spot-futures-spread': {
    title: 'Spot-Futures Spread Module',
    icon: <CurrencyExchangeIcon sx={{ color: '#34D399' }} />,
    color: '#064E3B',
  },
  'dex-futures-spread': {
    title: 'DEX-Futures Arbitrage Module',
    icon: <HubIcon sx={{ color: '#F472B6' }} />,
    color: '#831843',
  },
  'funding-spread': {
    title: 'Funding Rate Divergence Module',
    icon: <ShowChartIcon sx={{ color: '#FBBF24' }} />,
    color: '#78350F',
  },
};

interface ModuleFormState {
  threshold: string;
  status: string;
  reference_price_mode: string;
  max_price_ratio: string;
  isDirty: boolean;
  isSaving: boolean;
}

export const ModulesPage: React.FC = () => {
  const { data: modules, loading, error, refetch } = usePolling({
    fn: api.getModules,
    intervalMs: 20000,
  });

  const [formStates, setFormStates] = useState<Record<string, ModuleFormState>>({});
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' }>({
    open: false,
    message: '',
    severity: 'success',
  });

  // Sync initial module data into form states
  useEffect(() => {
    if (modules) {
      setFormStates((prev) => {
        const next = { ...prev };
        for (const mod of modules) {
          if (!next[mod.module_id] || !next[mod.module_id].isDirty) {
            next[mod.module_id] = {
              threshold: mod.threshold || '4.00',
              status: mod.status || 'active',
              reference_price_mode: mod.reference_price_mode || 'AVERAGE',
              max_price_ratio: mod.max_price_ratio || '2.00',
              isDirty: false,
              isSaving: false,
            };
          }
        }
        return next;
      });
    }
  }, [modules]);

  const handleFieldChange = (
    moduleId: string,
    field: keyof Omit<ModuleFormState, 'isDirty' | 'isSaving'>,
    value: string
  ) => {
    setFormStates((prev) => {
      const current = prev[moduleId] || {
        threshold: '4.00',
        status: 'active',
        reference_price_mode: 'AVERAGE',
        max_price_ratio: '2.00',
        isDirty: false,
        isSaving: false,
      };
      return {
        ...prev,
        [moduleId]: {
          ...current,
          [field]: value,
          isDirty: true,
        },
      };
    });
  };

  const handleApplyPreset = (moduleId: string, presetValue: string) => {
    handleFieldChange(moduleId, 'threshold', presetValue);
  };

  const handleSaveModule = async (moduleId: string) => {
    const form = formStates[moduleId];
    if (!form) return;

    const threshNum = parseFloat(form.threshold);
    if (isNaN(threshNum) || threshNum <= 0) {
      setSnackbar({
        open: true,
        message: 'Помилка: Поріг спреду повинен бути додатним числовим значенням (> 0)',
        severity: 'error',
      });
      return;
    }

    setFormStates((prev) => ({
      ...prev,
      [moduleId]: { ...prev[moduleId], isSaving: true },
    }));

    try {
      const payload: ModuleConfigUpdateRequest = {
        threshold: threshNum,
        status: form.status,
        reference_price_mode: form.reference_price_mode,
        max_price_ratio: parseFloat(form.max_price_ratio) || 2.0,
      };

      await api.updateModuleConfig(moduleId, payload);

      setFormStates((prev) => ({
        ...prev,
        [moduleId]: { ...prev[moduleId], isDirty: false, isSaving: false },
      }));

      setSnackbar({
        open: true,
        message: `Налаштування для модуля "${moduleId}" успішно оновлено!`,
        severity: 'success',
      });
      refetch();
    } catch (err: unknown) {
      setFormStates((prev) => ({
        ...prev,
        [moduleId]: { ...prev[moduleId], isSaving: false },
      }));
      const msg = err instanceof Error ? err.message : 'Не вдалося зберегти налаштування';
      setSnackbar({
        open: true,
        message: `Помилка збереження: ${msg}`,
        severity: 'error',
      });
    }
  };

  return (
    <Box>
      <Box sx={{ mb: 3, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 0.5 }}>
            <TuneIcon color="primary" sx={{ fontSize: 28 }} />
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              Налаштування модулів виявлення аномалій (Rule Engine Config)
            </Typography>
          </Box>
          <Typography variant="body2" color="text.secondary">
            Керування активністю та мінімальними порогами спреду для автономних модулів аналізу потокових даних.
          </Typography>
        </Box>
        <Button
          variant="outlined"
          startIcon={<RefreshIcon />}
          onClick={refetch}
          disabled={loading}
          size="small"
        >
          Оновити
        </Button>
      </Box>

      {error && <ErrorBanner message={error} onRetry={refetch} />}

      <Grid container spacing={3}>
        {loading && !modules
          ? Array.from({ length: 4 }).map((_, index) => (
              <Grid item xs={12} md={6} key={index}>
                <Card sx={{ p: 3, border: '1px solid #1F2937' }}>
                  <Skeleton variant="text" width="60%" height={32} />
                  <Skeleton variant="text" width="90%" height={20} />
                  <Skeleton variant="rectangular" height={80} sx={{ mt: 2, borderRadius: 1 }} />
                </Card>
              </Grid>
            ))
          : modules?.map((mod) => {
              const meta = MODULE_TITLES[mod.module_id] || {
                title: mod.module_id,
                icon: <ExtensionIcon color="primary" />,
                color: '#1F2937',
              };
              const form = formStates[mod.module_id] || {
                threshold: mod.threshold || '4.00',
                status: mod.status || 'active',
                reference_price_mode: mod.reference_price_mode || 'AVERAGE',
                max_price_ratio: mod.max_price_ratio || '2.00',
                isDirty: false,
                isSaving: false,
              };
              const isFunding = mod.module_id === 'funding-spread';
              const presets = isFunding
                ? ['0.0050', '0.0100', '0.0200', '0.0500', '0.1000']
                : ['2.00', '3.00', '4.00', '5.00', '8.00', '10.00'];

              return (
                <Grid item xs={12} md={6} key={mod.module_id}>
                  <Card
                    sx={{
                      height: '100%',
                      border: form.isDirty ? '1px solid #3B82F6' : '1px solid #1F2937',
                      transition: 'border-color 0.2s',
                    }}
                  >
                    <CardContent sx={{ p: 3 }}>
                      {/* Card Header */}
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                          {meta.icon}
                          <Box>
                            <Typography variant="subtitle1" sx={{ fontWeight: 700, lineHeight: 1.2 }}>
                              {meta.title}
                            </Typography>
                            <Typography variant="caption" sx={{ fontFamily: 'monospace', color: 'text.secondary' }}>
                              {mod.module_id}
                            </Typography>
                          </Box>
                        </Box>
                        <FormControlLabel
                          control={
                            <Switch
                              checked={form.status === 'active'}
                              onChange={(e) =>
                                handleFieldChange(mod.module_id, 'status', e.target.checked ? 'active' : 'paused')
                              }
                              color="success"
                            />
                          }
                          label={
                            <Typography variant="body2" sx={{ fontWeight: 600 }}>
                              {form.status === 'active' ? 'Активний' : 'Вимкнено'}
                            </Typography>
                          }
                        />
                      </Box>

                      {/* Description */}
                      <Typography variant="body2" color="text.secondary" sx={{ mb: 2.5, minHeight: 40 }}>
                        {mod.description}
                      </Typography>

                      <Divider sx={{ mb: 2.5, borderColor: '#1F2937' }} />

                      {/* Controls Area */}
                      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        {/* Threshold Input */}
                        <Box>
                          <Typography variant="caption" sx={{ fontWeight: 600, color: 'text.secondary', display: 'block', mb: 0.5 }}>
                            {isFunding ? 'Мінімальна розбіжність Funding Rate (%)' : 'Мінімальний поріг спреду за ціною (%)'}
                          </Typography>
                          <TextField
                            fullWidth
                            size="small"
                            type="number"
                            inputProps={{ step: isFunding ? '0.001' : '0.1', min: '0.0001' }}
                            value={form.threshold}
                            onChange={(e) => handleFieldChange(mod.module_id, 'threshold', e.target.value)}
                            InputProps={{
                              endAdornment: <InputAdornment position="end">%</InputAdornment>,
                            }}
                            helperText={
                              isFunding
                                ? 'Аномалія фіксується, якщо |Funding1 - Funding2| >= Threshold'
                                : 'Аномалія фіксується, якщо |P1 - P2| / Pref * 100% >= Threshold'
                            }
                          />

                          {/* Quick Presets */}
                          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75, mt: 1 }}>
                            <Typography variant="caption" sx={{ alignSelf: 'center', color: 'text.secondary', mr: 0.5 }}>
                              Пресет:
                            </Typography>
                            {presets.map((p) => (
                              <Chip
                                key={p}
                                label={`${p}%`}
                                size="small"
                                clickable
                                variant={form.threshold === p ? 'filled' : 'outlined'}
                                color={form.threshold === p ? 'primary' : 'default'}
                                onClick={() => handleApplyPreset(mod.module_id, p)}
                                sx={{ fontSize: '0.75rem', height: 22 }}
                              />
                            ))}
                          </Box>
                        </Box>

                        {/* Mode & Homonym Filter Row */}
                        <Grid container spacing={1.5}>
                          {!isFunding && (
                            <Grid item xs={12} sm={6}>
                              <FormControl fullWidth size="small">
                                <InputLabel>Розрахунок ціни (Pref)</InputLabel>
                                <Select
                                  value={form.reference_price_mode}
                                  label="Розрахунок ціни (Pref)"
                                  onChange={(e) =>
                                    handleFieldChange(mod.module_id, 'reference_price_mode', e.target.value)
                                  }
                                >
                                  <MenuItem value="AVERAGE">AVERAGE (Середня)</MenuItem>
                                  <MenuItem value="FIRST">FIRST (Перша біржа)</MenuItem>
                                  <MenuItem value="SECOND">SECOND (Друга біржа)</MenuItem>
                                  <MenuItem value="LAST">LAST (Остання)</MenuItem>
                                </Select>
                              </FormControl>
                            </Grid>
                          )}

                          {!isFunding && (
                            <Grid item xs={12} sm={6}>
                              <FormControl fullWidth size="small">
                                <InputLabel>Фільтр омонімів (Max Ratio)</InputLabel>
                                <Select
                                  value={form.max_price_ratio}
                                  label="Фільтр омонімів (Max Ratio)"
                                  onChange={(e) =>
                                    handleFieldChange(mod.module_id, 'max_price_ratio', e.target.value)
                                  }
                                >
                                  <MenuItem value="2.00">2.0x (Відхиляти &gt; 2x)</MenuItem>
                                  <MenuItem value="3.00">3.0x (Відхиляти &gt; 3x)</MenuItem>
                                  <MenuItem value="5.00">5.0x (Відхиляти &gt; 5x)</MenuItem>
                                </Select>
                              </FormControl>
                            </Grid>
                          )}
                        </Grid>

                        {/* Save Action */}
                        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mt: 1 }}>
                          <Box sx={{ display: 'flex', gap: 1 }}>
                            <Chip label="Deterministic" size="small" variant="outlined" sx={{ fontSize: '0.7rem' }} />
                            <Chip label="Rule-Based" size="small" variant="outlined" sx={{ fontSize: '0.7rem' }} />
                          </Box>
                          <Button
                            variant="contained"
                            color={form.isDirty ? 'primary' : 'inherit'}
                            startIcon={form.isSaving ? <CircularProgress size={16} color="inherit" /> : <SaveIcon />}
                            disabled={!form.isDirty || form.isSaving}
                            onClick={() => handleSaveModule(mod.module_id)}
                            size="small"
                            sx={{ fontWeight: 600 }}
                          >
                            {form.isSaving ? 'Збереження...' : form.isDirty ? 'Зберегти зміни' : 'Збережено'}
                          </Button>
                        </Box>
                      </Box>
                    </CardContent>
                  </Card>
                </Grid>
              );
            })}
      </Grid>

      {/* Feedback Snackbar */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={4000}
        onClose={() => setSnackbar((prev) => ({ ...prev, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert
          severity={snackbar.severity}
          onClose={() => setSnackbar((prev) => ({ ...prev, open: false }))}
          sx={{ width: '100%' }}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
};
