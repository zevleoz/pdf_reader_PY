import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { BootProvider } from "@/lib/boot";
import AppShell from "@/shell/AppShell";
import Kit from "@/pages/Kit";
import Students from "@/pages/Students";
import Questionnaires from "@/pages/Questionnaires";
import StudentProfile from "@/pages/StudentProfile";
import Flow from "@/pages/Flow";
import Workbench from "@/pages/Workbench";
import Booking from "@/pages/Booking";
import QuestionnaireBank from "@/pages/QuestionnaireBank";
import Users from "@/pages/Users";
import Minutes from "@/pages/Minutes";
import FirstTouch from "@/pages/first-touch/FirstTouch";
import NotFound from "@/pages/NotFound";

export default function App() {
  return (
    <TooltipProvider>
      <BrowserRouter basename="/app" future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <BootProvider>
          <Routes>
            <Route element={<AppShell />}>
              <Route index element={<Navigate to="/workbench" replace />} />
              <Route path="students" element={<Students />} />
              <Route path="questionnaires" element={<Questionnaires />} />
              <Route path="students/:code" element={<StudentProfile />} />
              <Route path="flow" element={<Flow />} />
              <Route path="workbench" element={<Workbench />} />
              <Route path="booking" element={<Booking />} />
              <Route path="minutes" element={<Minutes />} />
              <Route path="first-touch/students/:sid" element={<FirstTouch />} />
              <Route path="questionnaire-bank" element={<QuestionnaireBank />} />
              <Route path="users" element={<Users />} />
              <Route path="kit" element={<Kit />} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </BootProvider>
      </BrowserRouter>
    </TooltipProvider>
  );
}
