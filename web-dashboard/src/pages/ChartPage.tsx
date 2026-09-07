/**
 * Interactive Historical Price and Spread Divergence Chart page.
 * Powered by TradingView Lightweight Charts with horizontal time scrolling and timeframe buttons.
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Box,
  Typography,
  Card,
  CardContent,
  Grid,
  Button,
  ButtonGroup,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Chip,
  CircularProgress,
  Switch,
  FormControlLabel,
  Divider,
  Paper,
} from '@mui/material';
import ShowChartIcon from '@mui/icons-material/ShowChart';
import RefreshIcon from '@mui/icons-material/Refresh';
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import TimelineIcon from '@mui/icons-material/Timeline';
import TimerIcon from '@mui/icons-material/Timer';

import { createChart, LineSeries, AreaSeries, ColorType, LineStyle, CrosshairMode, IChartApi, ISeriesApi } from 'lightweight-charts';
import { api } from '../api/endpoints';
import { ErrorBanner } from '../components/ErrorBanner';
import type { ChartHistoryResponse, ChartPoint } from '../types/api';

const TIMEFRAMES = ['10s', '1m', '15m', '1h', '24h'] as const;
type Timeframe = typeof TIMEFRAMES[number];

const POPULAR_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'DOGEUSDT', 'XRPUSDT'];

export const ChartPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();

  const initialAsset = searchParams.get('asset') || 'BTC';
  const initialSymbol = searchParams.get('symbol') || 'BTCUSDT';
  const initialModule = searchParams.get('module') || 'futures-futures-spread';
  const initialTf = (searchParams.get('timeframe') as Timeframe) || '1h';

  const [asset, setAsset] = useState<string>(initialAsset);
  const [symbol, setSymbol] = useState<string>(initialSymbol);
  const [moduleId, setModuleId] = useState<string>(initialModule);
  const [timeframe, setTimeframe] = useState<Timeframe>(initialTf);
  const [autoRefresh, setAutoRefresh] = useState<boolean>(true);

  const [data, setData] = useState<ChartHistoryResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Chart DOM containers
  const priceChartContainerRef = useRef<HTMLDivElement>(null);
  const spreadChartContainerRef = useRef<HTMLDivElement>(null);

  // Chart instance references
  const priceChartRef = useRef<IChartApi | null>(null);
  const spreadChartRef = useRef<IChartApi | null>(null);
  const line1SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const line2SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const spreadSeriesRef = useRef<ISeriesApi<'Area'> | null>(null);

  // Update query params in URL
  const updateUrlParams = useCallback(
    (newAsset: string, newSymbol: string, newMod: string, newTf: Timeframe) => {
      setSearchParams({
        asset: newAsset,
        symbol: newSymbol,
        module: newMod,
        timeframe: newTf,
      });
    },
    [setSearchParams]
  );

  // Fetch chart data
  const fetchData = useCallback(async () => {
    try {
      setError(null);
      const res = await api.getChartHistory({
        asset,
        symbol,
        module_id: moduleId,
        timeframe,
      });
      setData(res);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Не вдалося завантажити історичні дані графіка';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [asset, symbol, moduleId, timeframe]);

  // Initial load and polling
  useEffect(() => {
    fetchData();
    if (!autoRefresh) return;
    const interval = setInterval(fetchData, 4000);
    return () => clearInterval(interval);
  }, [fetchData, autoRefresh]);

  // Initialize and update Lightweight Charts
  useEffect(() => {
    if (!priceChartContainerRef.current || !spreadChartContainerRef.current) return;

    // Clean up previous charts
    if (priceChartRef.current) {
      priceChartRef.current.remove();
      priceChartRef.current = null;
    }
    if (spreadChartRef.current) {
      spreadChartRef.current.remove();
      spreadChartRef.current = null;
    }

    const commonChartOptions = {
      layout: {
        background: { type: ColorType.Solid, color: '#111827' },
        textColor: '#9CA3AF',
      },
      grid: {
        vertLines: { color: '#1F2937' },
        horzLines: { color: '#1F2937' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: '#4B5563', width: 1 as const, style: LineStyle.Dashed },
        horzLine: { color: '#4B5563', width: 1 as const, style: LineStyle.Dashed },
      },
      timeScale: {
        borderColor: '#1F2937',
        timeVisible: true,
        secondsVisible: true,
      },
    };

    // 1. Top Price Comparison Chart
    const priceChart = createChart(priceChartContainerRef.current, {
      ...commonChartOptions,
      height: 320,
      rightPriceScale: {
        borderColor: '#1F2937',
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
    });

    const line1 = priceChart.addSeries(LineSeries, {
      color: '#3B82F6', // Blue for Source 1
      lineWidth: 2,
      title: 'Джерело 1',
    });

    const line2 = priceChart.addSeries(LineSeries, {
      color: '#10B981', // Green for Source 2
      lineWidth: 2,
      title: 'Джерело 2',
    });

    priceChartRef.current = priceChart;
    line1SeriesRef.current = line1;
    line2SeriesRef.current = line2;

    // 2. Bottom Spread Divergence Chart
    const spreadChart = createChart(spreadChartContainerRef.current, {
      ...commonChartOptions,
      height: 220,
      rightPriceScale: {
        borderColor: '#1F2937',
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
    });

    const spreadSeries = spreadChart.addSeries(AreaSeries, {
      topColor: 'rgba(239, 68, 68, 0.4)',
      bottomColor: 'rgba(239, 68, 68, 0.0)',
      lineColor: '#EF4444',
      lineWidth: 2,
      title: 'Спред %',
    });

    spreadChartRef.current = spreadChart;
    spreadSeriesRef.current = spreadSeries;

    // Synchronize horizontal scrolling between charts
    priceChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range && spreadChart) {
        spreadChart.timeScale().setVisibleLogicalRange(range);
      }
    });

    spreadChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range && priceChart) {
        priceChart.timeScale().setVisibleLogicalRange(range);
      }
    });

    // Handle Resize
    const handleResize = () => {
      if (priceChartContainerRef.current && priceChart) {
        priceChart.applyOptions({ width: priceChartContainerRef.current.clientWidth });
      }
      if (spreadChartContainerRef.current && spreadChart) {
        spreadChart.applyOptions({ width: spreadChartContainerRef.current.clientWidth });
      }
    };

    window.addEventListener('resize', handleResize);
    handleResize();

    return () => {
      window.removeEventListener('resize', handleResize);
      priceChart.remove();
      spreadChart.remove();
    };
  }, []);

  // Update chart timeseries data points
  useEffect(() => {
    if (!data || !line1SeriesRef.current || !line2SeriesRef.current || !spreadSeriesRef.current) return;

    const points = data.points || [];
    if (points.length === 0) return;

    // Ensure strictly unique, sorted timestamps for Lightweight Charts
    const uniquePointsMap = new Map<number, ChartPoint>();
    for (const pt of points) {
      uniquePointsMap.set(pt.time_epoch, pt);
    }
    const sortedPoints = Array.from(uniquePointsMap.values()).sort((a, b) => a.time_epoch - b.time_epoch);

    const line1Data: { time: number; value: number }[] = [];
    const line2Data: { time: number; value: number }[] = [];
    const spreadData: { time: number; value: number }[] = [];

    let src1Title = 'Джерело 1';
    let src2Title = 'Джерело 2';

    for (const pt of sortedPoints) {
      const time = pt.time_epoch as unknown as number;
      if (pt.price_1 !== null && pt.price_1 !== undefined) {
        line1Data.push({ time, value: parseFloat(String(pt.price_1)) });
        if (pt.source_1) src1Title = pt.source_1.toUpperCase();
      }
      if (pt.price_2 !== null && pt.price_2 !== undefined) {
        line2Data.push({ time, value: parseFloat(String(pt.price_2)) });
        if (pt.source_2) src2Title = pt.source_2.toUpperCase();
      }
      if (pt.spread_percent !== null && pt.spread_percent !== undefined) {
        spreadData.push({ time, value: parseFloat(String(pt.spread_percent)) });
      }
    }

    line1SeriesRef.current.applyOptions({ title: src1Title });
    line2SeriesRef.current.applyOptions({ title: src2Title });

    line1SeriesRef.current.setData(line1Data as unknown as Parameters<ISeriesApi<'Line'>['setData']>[0]);
    line2SeriesRef.current.setData(line2Data as unknown as Parameters<ISeriesApi<'Line'>['setData']>[0]);
    spreadSeriesRef.current.setData(spreadData as unknown as Parameters<ISeriesApi<'Area'>['setData']>[0]);

    // Add threshold price line on spread chart
    if (points.length > 0 && points[0].threshold) {
      const threshVal = parseFloat(String(points[0].threshold));
      spreadSeriesRef.current.createPriceLine({
        price: threshVal,
        color: '#F59E0B',
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: `Поріг (${threshVal}%)`,
      });
    }

    // Fit content
    if (priceChartRef.current) priceChartRef.current.timeScale().fitContent();
    if (spreadChartRef.current) spreadChartRef.current.timeScale().fitContent();
  }, [data]);

  const handleSymbolChange = (newSym: string) => {
    const cleanSym = newSym.trim().toUpperCase();
    const cleanAsset = cleanSym.replace(/(USDT|USDC|USD|BUSD)$/, '') || cleanSym;
    setSymbol(cleanSym);
    setAsset(cleanAsset);
    updateUrlParams(cleanAsset, cleanSym, moduleId, timeframe);
  };

  const handleTimeframeChange = (newTf: Timeframe) => {
    setTimeframe(newTf);
    updateUrlParams(asset, symbol, moduleId, newTf);
  };

  const handleModuleChange = (newMod: string) => {
    setModuleId(newMod);
    updateUrlParams(asset, symbol, newMod, timeframe);
  };

  // Helper formatting for duration badge
  const formatDuration = (seconds: number | null) => {
    if (!seconds || seconds <= 0) return 'Щойно виник (< 10 сек)';
    if (seconds < 60) return `Триває: ${seconds} сек`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    if (mins < 60) return `Триває: ${mins} хв ${secs} сек (Стійкий)`;
    const hours = Math.floor(mins / 60);
    return `Триває: ${hours} год ${mins % 60} хв (Стійкий)`;
  };

  const isCurrentAnomaly = data && data.points.length > 0 && data.points[data.points.length - 1].is_anomaly;

  return (
    <Box>
      {/* Header */}
      <Box sx={{ mb: 3, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 2 }}>
        <Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 0.5 }}>
            <ShowChartIcon color="primary" sx={{ fontSize: 32 }} />
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              Історичний графік розходження цін (Price & Spread Divergence)
            </Typography>
          </Box>
          <Typography variant="body2" color="text.secondary">
            Аналіз динаміки та сталості спреду між біржами з горизонтальним гортанням у часі (TradingView Engine).
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <FormControlLabel
            control={
              <Switch
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                color="primary"
                size="small"
              />
            }
            label={<Typography variant="body2">Автооновлення (Live)</Typography>}
          />
          <Button
            variant="outlined"
            size="small"
            startIcon={loading ? <CircularProgress size={16} /> : <RefreshIcon />}
            onClick={fetchData}
            disabled={loading}
          >
            Оновити
          </Button>
        </Box>
      </Box>

      {error && <ErrorBanner message={error} onRetry={fetchData} />}

      {/* Controls Bar */}
      <Paper sx={{ p: 2.5, mb: 3, border: '1px solid #1F2937', backgroundColor: '#111827' }}>
        <Grid container spacing={2} alignItems="center">
          {/* Symbol Input & Quick Chips */}
          <Grid item xs={12} md={4}>
            <TextField
              fullWidth
              size="small"
              label="Торгова пара (Symbol)"
              value={symbol}
              onChange={(e) => handleSymbolChange(e.target.value)}
              placeholder="BTCUSDT, ETHUSDT..."
              sx={{ mb: 1 }}
            />
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
              {POPULAR_SYMBOLS.map((s) => (
                <Chip
                  key={s}
                  label={s}
                  size="small"
                  clickable
                  variant={symbol === s ? 'filled' : 'outlined'}
                  color={symbol === s ? 'primary' : 'default'}
                  onClick={() => handleSymbolChange(s)}
                  sx={{ fontSize: '0.75rem', height: 22 }}
                />
              ))}
            </Box>
          </Grid>

          {/* Module Selector */}
          <Grid item xs={12} md={4}>
            <FormControl fullWidth size="small">
              <InputLabel>Модуль аналізу</InputLabel>
              <Select
                value={moduleId}
                label="Модуль аналізу"
                onChange={(e) => handleModuleChange(e.target.value)}
              >
                <MenuItem value="futures-futures-spread">Futures-Futures Spread Module</MenuItem>
                <MenuItem value="spot-futures-spread">Spot-Futures Spread Module</MenuItem>
                <MenuItem value="dex-futures-spread">DEX-Futures Arbitrage Module</MenuItem>
                <MenuItem value="funding-spread">Funding Rate Divergence Module</MenuItem>
              </Select>
            </FormControl>
          </Grid>

          {/* Timeframe Buttons */}
          <Grid item xs={12} md={4}>
            <Typography variant="caption" sx={{ display: 'block', mb: 0.5, color: 'text.secondary', fontWeight: 600 }}>
              Часовий інтервал (Timeframe):
            </Typography>
            <ButtonGroup variant="outlined" size="small" fullWidth>
              {TIMEFRAMES.map((tf) => (
                <Button
                  key={tf}
                  variant={timeframe === tf ? 'contained' : 'outlined'}
                  onClick={() => handleTimeframeChange(tf)}
                  sx={{ fontWeight: 600 }}
                >
                  {tf}
                </Button>
              ))}
            </ButtonGroup>
          </Grid>
        </Grid>
      </Paper>

      {/* Analytics Summary Banner */}
      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} sm={6} md={3}>
          <Card sx={{ border: '1px solid #1F2937', height: '100%' }}>
            <CardContent sx={{ p: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5, color: 'text.secondary' }}>
                <TrendingUpIcon fontSize="small" color="primary" />
                <Typography variant="caption" sx={{ fontWeight: 600 }}>
                  Поточний спред
                </Typography>
              </Box>
              <Typography variant="h5" sx={{ fontWeight: 700, color: isCurrentAnomaly ? '#EF4444' : '#10B981' }}>
                {data?.current_spread !== null && data?.current_spread !== undefined
                  ? `+${parseFloat(String(data.current_spread)).toFixed(2)}%`
                  : '—'}
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card sx={{ border: '1px solid #1F2937', height: '100%' }}>
            <CardContent sx={{ p: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5, color: 'text.secondary' }}>
                <TimelineIcon fontSize="small" sx={{ color: '#F59E0B' }} />
                <Typography variant="caption" sx={{ fontWeight: 600 }}>
                  Максимальний пік ({timeframe})
                </Typography>
              </Box>
              <Typography variant="h5" sx={{ fontWeight: 700 }}>
                {data?.max_spread !== null && data?.max_spread !== undefined
                  ? `+${parseFloat(String(data.max_spread)).toFixed(2)}%`
                  : '—'}
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card sx={{ border: '1px solid #1F2937', height: '100%' }}>
            <CardContent sx={{ p: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5, color: 'text.secondary' }}>
                <AccessTimeIcon fontSize="small" color="info" />
                <Typography variant="caption" sx={{ fontWeight: 600 }}>
                  Середній спред ({timeframe})
                </Typography>
              </Box>
              <Typography variant="h5" sx={{ fontWeight: 700 }}>
                {data?.avg_spread !== null && data?.avg_spread !== undefined
                  ? `+${parseFloat(String(data.avg_spread)).toFixed(2)}%`
                  : '—'}
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card
            sx={{
              border: isCurrentAnomaly ? '1px solid #EF4444' : '1px solid #1F2937',
              backgroundColor: isCurrentAnomaly ? 'rgba(239, 68, 68, 0.05)' : undefined,
              height: '100%',
            }}
          >
            <CardContent sx={{ p: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5, color: 'text.secondary' }}>
                <TimerIcon fontSize="small" color={isCurrentAnomaly ? 'error' : 'action'} />
                <Typography variant="caption" sx={{ fontWeight: 600 }}>
                  Сталість розходження
                </Typography>
              </Box>
              <Typography
                variant="subtitle1"
                sx={{
                  fontWeight: 700,
                  color: isCurrentAnomaly ? '#EF4444' : '#10B981',
                  lineHeight: 1.3,
                }}
              >
                {isCurrentAnomaly ? formatDuration(data?.spread_duration_seconds ?? 0) : 'В межах норми'}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Chart Canvas Area */}
      <Card sx={{ border: '1px solid #1F2937', mb: 3 }}>
        <CardContent sx={{ p: 2.5 }}>
          {/* Price Chart Header */}
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                1. Порівняння цін між біржами ($)
              </Typography>
              <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'center' }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <Box sx={{ width: 12, height: 3, backgroundColor: '#3B82F6', borderRadius: 1 }} />
                  <Typography variant="caption" color="text.secondary">Джерело 1 (Binance/DEX)</Typography>
                </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <Box sx={{ width: 12, height: 3, backgroundColor: '#10B981', borderRadius: 1 }} />
                  <Typography variant="caption" color="text.secondary">Джерело 2 (Bybit Futures)</Typography>
                </Box>
              </Box>
            </Box>
            <Typography variant="caption" color="text.secondary">
              💡 Гортайте вліво/вправо мишкою для перегляду історії, коліщатко — масштаб
            </Typography>
          </Box>

          <div ref={priceChartContainerRef} style={{ width: '100%', position: 'relative' }} />

          <Divider sx={{ my: 2.5, borderColor: '#1F2937' }} />

          {/* Spread Divergence Header */}
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                2. Динаміка спреду (% Divergence)
              </Typography>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                <Box sx={{ width: 12, height: 2, backgroundColor: '#F59E0B', borderTop: '2px dashed #F59E0B' }} />
                <Typography variant="caption" color="text.secondary">Лінія порогу аномалії</Typography>
              </Box>
            </Box>
          </Box>

          <div ref={spreadChartContainerRef} style={{ width: '100%', position: 'relative' }} />
        </CardContent>
      </Card>
    </Box>
  );
};
