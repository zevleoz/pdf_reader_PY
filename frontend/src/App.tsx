import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { BootProvider } from "@/lib/boot";
import AppShell from "@/shell/AppShell";
import Kit from "@/pages/Kit";
import Students from "@/pages/Students";
import StudentProfile from "@/pages/StudentProfile";
import Flow from "@/pages/Flow";
import NotFound from "@/pages/NotFound";

export default function App() {
  return (
    <TooltipProvider>
      <BrowserRouter basename="/app" future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <BootProvider>
          <Routes>
            <Route element={<AppShell />}>
              <Route index element={<Navigate to="/students" replace />} />
              <Route path="students" element={<Students />} />
              <Route path="students/:code" element={<StudentProfile />} />
              <Route path="flow" element={<Flow />} />
              <Route path="kit" element={<Kit />} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </BootProvider>
      </BrowserRouter>
    </TooltipProvider>
  );
}
