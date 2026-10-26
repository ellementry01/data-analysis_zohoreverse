import { Navigate, Route, Routes } from "react-router-dom";
import WorkspacesPage from "./pages/WorkspacesPage";
import WorkspaceLayout from "./pages/WorkspaceLayout";
import OverviewPage from "./pages/OverviewPage";
import DataPage from "./pages/DataPage";
import DatasetPage from "./pages/DatasetPage";
import ImportPage from "./pages/ImportPage";
import ModelPage from "./pages/ModelPage";
import SqlPage from "./pages/SqlPage";
import SemanticPage from "./pages/SemanticPage";
import ReportsPage from "./pages/ReportsPage";
import ReportEditor from "./pages/ReportEditor";
import DashboardsPage from "./pages/DashboardsPage";
import DashboardView from "./pages/DashboardView";
import AskPage from "./pages/AskPage";
import LineagePage from "./pages/LineagePage";
import HistoryPage from "./pages/HistoryPage";
import SettingsPage from "./pages/SettingsPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<WorkspacesPage />} />
      <Route path="/w/:wsId" element={<WorkspaceLayout />}>
        <Route index element={<OverviewPage />} />
        <Route path="data" element={<DataPage />} />
        <Route path="data/:dsId" element={<DatasetPage />} />
        <Route path="import" element={<ImportPage />} />
        <Route path="model" element={<ModelPage />} />
        <Route path="sql" element={<SqlPage />} />
        <Route path="semantic" element={<SemanticPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="reports/:reportId" element={<ReportEditor />} />
        <Route path="dashboards" element={<DashboardsPage />} />
        <Route path="dashboards/:dashId" element={<DashboardView />} />
        <Route path="ask" element={<AskPage />} />
        <Route path="ask/:convId" element={<AskPage />} />
        <Route path="lineage" element={<LineagePage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" />} />
    </Routes>
  );
}
