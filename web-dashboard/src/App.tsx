/**
 * Root Application router and theme provider.
 */

import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ThemeProvider, CssBaseline } from '@mui/material';
import { theme } from './theme/theme';
import { MainLayout } from './layouts/MainLayout';
import { OverviewPage } from './pages/OverviewPage';
import { DetectionsPage } from './pages/DetectionsPage';
import { AggregatesPage } from './pages/AggregatesPage';
import { AlertsPage } from './pages/AlertsPage';
import { ModulesPage } from './pages/ModulesPage';
import { MetricsPage } from './pages/MetricsPage';
import { ChartPage } from './pages/ChartPage';

export const App: React.FC = () => {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<MainLayout />}>
            <Route index element={<OverviewPage />} />
            <Route path="detections" element={<DetectionsPage />} />
            <Route path="aggregates" element={<AggregatesPage />} />
            <Route path="alerts" element={<AlertsPage />} />
            <Route path="charts" element={<ChartPage />} />
            <Route path="modules" element={<ModulesPage />} />
            <Route path="metrics" element={<MetricsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
};

export default App;
