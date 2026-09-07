import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { StatusChip } from '../src/components/StatusChip';
import { MetricCard } from '../src/components/MetricCard';
import { ErrorBanner } from '../src/components/ErrorBanner';
import { DataTable } from '../src/components/DataTable';
import { FilterToolbar } from '../src/components/FilterToolbar';

describe('UI Components', () => {
  it('renders StatusChip with correct label and variants', () => {
    render(<StatusChip status="ANOMALY" />);
    expect(screen.getByText('ANOMALY')).toBeInTheDocument();

    render(<StatusChip status="HIGH" />);
    expect(screen.getByText('HIGH')).toBeInTheDocument();

    render(<StatusChip status="NORMAL" />);
    expect(screen.getByText('NORMAL')).toBeInTheDocument();
  });

  it('renders MetricCard with title, value, and subtitle', () => {
    render(<MetricCard title="Total Detections" value={42} subtitle="Evaluated events" icon={<span>icon</span>} />);
    expect(screen.getByText('Total Detections')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
    expect(screen.getByText('Evaluated events')).toBeInTheDocument();
  });

  it('renders ErrorBanner with retry button and calls handler on click', () => {
    const onRetry = vi.fn();
    render(<ErrorBanner message="Connection refused" onRetry={onRetry} />);
    expect(screen.getByText('Connection refused')).toBeInTheDocument();
    const retryBtn = screen.getByRole('button', { name: /retry/i });
    expect(retryBtn).toBeInTheDocument();
    retryBtn.click();
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('renders DataTable with columns and empty state when no rows', () => {
    render(
      <DataTable
        columns={[{ id: 'id', label: 'ID' }, { id: 'name', label: 'Name' }]}
        rows={[]}
        total={0}
        page={0}
        rowsPerPage={10}
        onPageChange={vi.fn()}
        onRowsPerPageChange={vi.fn()}
        rowKey={(r: { id: string }) => r.id}
      />
    );
    expect(screen.getByText('ID')).toBeInTheDocument();
    expect(screen.getByText('Name')).toBeInTheDocument();
    expect(screen.getByText('No records found matching criteria')).toBeInTheDocument();
  });

  it('renders FilterToolbar with fields', () => {
    const onChange = vi.fn();
    const onReset = vi.fn();
    render(
      <FilterToolbar
        fields={[
          { id: 'asset', label: 'Asset', type: 'text', value: 'BTC' },
        ]}
        onChange={onChange}
        onReset={onReset}
      />
    );
    expect(screen.getByLabelText('Asset')).toBeInTheDocument();
    const clearBtn = screen.getByRole('button', { name: /clear filters/i });
    expect(clearBtn).toBeInTheDocument();
    clearBtn.click();
    expect(onReset).toHaveBeenCalledTimes(1);
  });
});
