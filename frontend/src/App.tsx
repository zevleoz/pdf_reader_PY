import * as React from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { BootProvider, useBoot } from "@/lib/boot";
import AppShell from "@/shell/AppShell";
import Kit from "@/pages/Kit";
import Students from "@/pages/Students";
import Questionnaires from "@/pages/Questionnaires";
import StudentProfile from "@/pages/StudentProfile";
import Workbench from "@/pages/Workbench";
import Booking from "@/pages/Booking";
import Handoff from "@/pages/Handoff";
import QuestionnaireBank from "@/pages/QuestionnaireBank";
import Users from "@/pages/Users";
import Settings from "@/pages/Settings";
import Minutes from "@/pages/Minutes";
import FirstTouch from "@/pages/first-touch/FirstTouch";
import NotFound from "@/pages/NotFound";

function Home() {
  const boot = useBoot();
  return <Navigate to={boot.user.role === "front" ? "/handoff" : "/workbench"} replace />;
}

/** 前台只能停留交接页：直达其他后台 URL 一律退回。 */
function FrontGate({ children }: { children: React.ReactNode }) {
  const boot = useBoot();
  const loc = useLocation();
  if (boot.user.role === "front" && !loc.pathname.startsWith("/handoff")) {
    return <Navigate to="/handoff" replace />;
  }
  return <>{children}</>;
}

/** 旧「Profiling 流程」地址：研究院回学生名单，前台沿用预约交接入口。 */
function FlowRedirect() {
  const boot = useBoot();
  return <Navigate to={boot.user.role === "front" ? "/handoff" : "/students"} replace />;
}

export default function App() {
  return (
    <TooltipProvider>
      <BrowserRouter basename="/app" future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <BootProvider>
          <FrontGate>
            <Routes>
              <Route element={<AppShell />}>
                <Route index element={<Home />} />
                <Route path="students" element={<Students />} />
                <Route path="questionnaires" element={<Questionnaires />} />
                <Route path="students/:code" element={<StudentProfile />} />
                <Route path="flow" element={<FlowRedirect />} />
                <Route path="workbench" element={<Workbench />} />
                <Route path="booking" element={<Booking />} />
                <Route path="handoff" element={<Handoff />} />
                <Route path="minutes" element={<Minutes />} />
                <Route path="first-touch/students/:sid" element={<FirstTouch />} />
                <Route path="questionnaire-bank" element={<QuestionnaireBank />} />
                <Route path="users" element={<Users />} />
                <Route path="settings" element={<Settings />} />
                <Route path="kit" element={<Kit />} />
                <Route path="*" element={<NotFound />} />
              </Route>
            </Routes>
          </FrontGate>
        </BootProvider>
      </BrowserRouter>
    </TooltipProvider>
  );
}
