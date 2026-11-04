import { Button } from "@/components/ui/button";
import PageHeader from "@/shell/PageHeader";

export default function NotFound() {
  return (
    <div>
      <PageHeader title="页面不存在" sub="你访问的页面不存在或已被移除。" />
      <Button variant="outline" asChild>
        <a href="/platforms">选择平台</a>
      </Button>
    </div>
  );
}
