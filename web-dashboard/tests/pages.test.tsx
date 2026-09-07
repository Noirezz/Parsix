import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { OverviewPage } from '../src/pages/OverviewPage';
import { DetectionsPage } from '../src/pages/DetectionsPage';
import { AggregatesPage } from '../src/pages/AggregatesPage';
import { AlertsPage } from '../src/pages/AlertsPage';
import { ModulesPage } from '../src/pages/ModulesPage';
import { MetricsPage } from '../src/pages/MetricsPage';
import { ChartPage } from '../src/pages/ChartPage';
import { api } from '../src/api/endpoints';

describe('Pages Rendering', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders OverviewPage with metrics cards and recent alerts', async () => {
    vi.spyOn(api, 'getMetrics').mockResolvedValue({
      total_processed_events: 100,
      total_detections: 250,
      detections_by_status: { ANOMALY: 15, NORMAL: 235 },
      detections_by_module: { 'spot-futures-spread': 250 },
      total_aggregates: 15,
      total_alerts: 10,
      alerts_by_priority: { HIGH: 8, MEDIUM: 2 },
      alerts_by_notification_status: { SENT: 10 },
    });

    vi.spyOn(api, 'getAlerts').mockResolvedValue({
      items: [
        {
          alert_id: 'alt-1',
          event_id: 'evt-1',
          timestamp: '2026-08-26T12:00:00Z',
          asset: 'BTC',
          priority: 'HIGH',
          title: 'Spot-Futures Spread Anomaly',
          summary: 'Spread 1.25% exceeded threshold',
          anomaly_score: '1.25',
          triggered_modules: ['spot-futures-spread'],
          details: {},
          notification_status: 'SENT',
          notification_attempts: 1,
          notified_at: '2026-08-26T12:00:02Z',
          last_notification_error: null,
          created_at: '2026-08-26T12:00:00Z',
        },
      ],
      total: 1,
      limit: 5,
      offset: 0,
    });

    vi.spyOn(api, 'getDetections').mockResolvedValue({
      items: [
        {
          result_id: 'det-1',
          event_id: 'evt-1',
          module_id: 'spot-futures-spread',
          timestamp: '2026-08-26T12:00:00Z',
          asset: 'BTC',
          metric_value: '1.25',
          threshold: '1.00',
          anomaly_ratio: '1.25',
          status: 'ANOMALY',
          persistence: 1,
          metadata: {},
        },
      ],
      total: 1,
      limit: 5,
      offset: 0,
    });

    render(
      <MemoryRouter>
        <OverviewPage />
      </MemoryRouter>
    );

    expect(screen.getByText('System Overview')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText('Spot-Futures Spread Anomaly')).toBeInTheDocument();
    });
  });

  it('renders DetectionsPage with table and filters', async () => {
    vi.spyOn(api, 'getDetections').mockResolvedValue({
      items: [
        {
          result_id: 'det-100',
          event_id: 'evt-100',
          module_id: 'futures-futures-spread',
          timestamp: '2026-08-26T12:00:00Z',
          asset: 'ETH',
          metric_value: '2.50',
          threshold: '1.00',
          anomaly_ratio: '2.50',
          status: 'ANOMALY',
          persistence: 1,
          metadata: {},
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });

    render(
      <MemoryRouter>
        <DetectionsPage />
      </MemoryRouter>
    );

    expect(screen.getByText('Module Detections')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText('det-100')).toBeInTheDocument();
      expect(screen.getByText('futures-futures-spread')).toBeInTheDocument();
    });
  });

  it('renders AggregatesPage with table', async () => {
    vi.spyOn(api, 'getAggregates').mockResolvedValue({
      items: [
        {
          aggregation_id: 'agg-100',
          timestamp: '2026-08-26T12:00:00Z',
          asset: 'BTC',
          composite_anomaly_score: '3.20',
          max_anomaly_ratio: '3.20',
          average_anomaly_ratio: '3.20',
          priority: 'HIGH',
          module_count: 2,
          triggered_modules: ['spot-futures-spread', 'funding-spread'],
          correlation_window: {},
          metadata: {},
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });

    render(
      <MemoryRouter>
        <AggregatesPage />
      </MemoryRouter>
    );

    expect(screen.getByText('Aggregated Anomaly Results')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText('agg-100')).toBeInTheDocument();
    });
  });

  it('renders AlertsPage with table', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue({
      items: [
        {
          alert_id: 'alt-500',
          event_id: 'evt-500',
          timestamp: '2026-08-26T12:00:00Z',
          asset: 'SOL',
          priority: 'HIGH',
          title: 'DEX-Futures Spread Anomaly',
          summary: 'Spread 5.0% exceeded threshold',
          anomaly_score: '5.0',
          triggered_modules: ['dex-futures-spread'],
          details: {},
          notification_status: 'SENT',
          notification_attempts: 1,
          notified_at: '2026-08-26T12:00:01Z',
          last_notification_error: null,
          created_at: '2026-08-26T12:00:00Z',
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });

    render(
      <MemoryRouter>
        <AlertsPage />
      </MemoryRouter>
    );

    expect(screen.getByText('Generated Alerts')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText('alt-500')).toBeInTheDocument();
    });
  });

  it('renders ModulesPage with registered MVP modules', async () => {
    vi.spyOn(api, 'getModules').mockResolvedValue([
      {
        module_id: 'futures-futures-spread',
        status: 'active',
        description: 'Detects anomalous futures price divergence',
        threshold: '4.00',
        reference_price_mode: 'AVERAGE',
        max_price_ratio: '2.00',
        updated_at: null,
      },
      {
        module_id: 'spot-futures-spread',
        status: 'active',
        description: 'Detects spot futures price divergence',
        threshold: '4.00',
        reference_price_mode: 'AVERAGE',
        max_price_ratio: '2.00',
        updated_at: null,
      },
      {
        module_id: 'dex-futures-spread',
        status: 'active',
        description: 'Detects DEX futures price divergence',
        threshold: '4.00',
        reference_price_mode: 'AVERAGE',
        max_price_ratio: '2.00',
        updated_at: null,
      },
      {
        module_id: 'funding-spread',
        status: 'active',
        description: 'Detects funding rate divergence',
        threshold: '0.0100',
        reference_price_mode: 'AVERAGE',
        max_price_ratio: '2.00',
        updated_at: null,
      },
    ]);

    render(
      <MemoryRouter>
        <ModulesPage />
      </MemoryRouter>
    );

    expect(screen.getByText(/Налаштування модулів виявлення аномалій/i)).toBeInTheDocument();
    expect(await screen.findByText('futures-futures-spread')).toBeInTheDocument();
    expect(await screen.findByText('spot-futures-spread')).toBeInTheDocument();
    expect(await screen.findByText('dex-futures-spread')).toBeInTheDocument();
    expect(await screen.findByText('funding-spread')).toBeInTheDocument();
  });

  it('renders MetricsPage with operational statistics', async () => {
    vi.spyOn(api, 'getMetrics').mockResolvedValue({
      total_processed_events: 5000,
      total_detections: 12000,
      detections_by_status: { ANOMALY: 450, NORMAL: 11550 },
      detections_by_module: {
        'futures-futures-spread': 3000,
        'spot-futures-spread': 3000,
        'dex-futures-spread': 3000,
        'funding-spread': 3000,
      },
      total_aggregates: 450,
      total_alerts: 120,
      alerts_by_priority: { HIGH: 50, MEDIUM: 50, LOW: 20 },
      alerts_by_notification_status: { SENT: 118, FAILED: 2 },
    });

    render(
      <MemoryRouter>
        <MetricsPage />
      </MemoryRouter>
    );

    expect(screen.getByText('Operational Metrics')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText('5000')).toBeInTheDocument();
      expect(screen.getByText('12000')).toBeInTheDocument();
    });
  });

  it('renders ChartPage with price and spread metrics', async () => {
    vi.spyOn(api, 'getChartHistory').mockResolvedValue({
      asset: 'BTC',
      symbol: 'BTCUSDT',
      module_id: 'futures-futures-spread',
      timeframe: '1h',
      points: [
        {
          timestamp: '2026-08-31T12:00:00Z',
          time_epoch: 1788110400,
          price_1: '68500.00',
          source_1: 'binance',
          price_2: '65200.00',
          source_2: 'bybit',
          spread_percent: '4.85',
          threshold: '4.00',
          is_anomaly: true,
        },
      ],
      current_spread: '4.85',
      max_spread: '4.85',
      avg_spread: '4.85',
      spread_duration_seconds: 120,
    });

    render(
      <MemoryRouter initialEntries={['/charts?symbol=BTCUSDT&asset=BTC']}>
        <ChartPage />
      </MemoryRouter>
    );

    expect(screen.getByText(/Історичний графік розходження цін/i)).toBeInTheDocument();
    expect(screen.getByText('10s')).toBeInTheDocument();
    expect(screen.getByText('1m')).toBeInTheDocument();
    expect(screen.getByText('15m')).toBeInTheDocument();
    expect(screen.getByText('1h')).toBeInTheDocument();
    expect(screen.getByText('24h')).toBeInTheDocument();
  });
});
