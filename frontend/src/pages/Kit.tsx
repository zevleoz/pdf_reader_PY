import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useTab } from "@/lib/useTab";
import PageHeader from "@/shell/PageHeader";

const tokens = [
  { name: "ink", hex: "#0E0E0E" },
  { name: "ink-2", hex: "#383838" },
  { name: "mute", hex: "#6A6A6A" },
  { name: "sunk", hex: "#F1F1F1" },
  { name: "line", hex: "#E2E2E2" },
  { name: "shell", hex: "#E2001A" },
  { name: "on-foreground", hex: "#C70017" },
  { name: "attention", hex: "#D00018" },
  { name: "tint", hex: "#FDECEE" },
  { name: "rail-m1", hex: "#0B3FD6" },
  { name: "rail-e4", hex: "#009A6E" },
];

const rows = [1, 2, 3];

export default function Kit() {
  const [tab, setTab] = useTab(["overview", "files"], "overview");
  return (
    <div>
      <PageHeader title="组件" sub="样式核对用，数据为示例。" />

      <h2 className="mt-10 mb-3 text-lg font-bold">颜色</h2>
      {tokens.map((token) => (
        <div key={token.name}>
          <div
            style={{ width: 48, height: 48, background: `hsl(var(--${token.name}))` }}
          />
          <div className="text-xs">{token.name}</div>
          <div className="text-xs">{token.hex}</div>
        </div>
      ))}

      <h2 className="mt-10 mb-3 text-lg font-bold">文字</h2>
      <div className="text-title">学生档案</div>
      <div className="text-title-sm">学生档案</div>
      <div>正文 14px：凭远 APP·ARK 0123456789</div>
      <div className="text-xs">说明文字 12px</div>

      <h2 className="mt-10 mb-3 text-lg font-bold">按钮</h2>
      <div>
        <Button variant="default">default</Button>
        <Button variant="destructive">destructive</Button>
        <Button variant="outline">outline</Button>
        <Button variant="secondary">secondary</Button>
        <Button variant="ghost">ghost</Button>
        <Button variant="link">link</Button>
      </div>
      <div>
        <Button size="sm">sm</Button>
        <Button size="default">default</Button>
        <Button size="lg">lg</Button>
        <Button disabled>disabled</Button>
      </div>

      <h2 className="mt-10 mb-3 text-lg font-bold">输入</h2>
      <div>
        <Label htmlFor="kit-name">姓名</Label>
        <Input id="kit-name" placeholder="输入姓名" />
      </div>

      <h2 className="mt-10 mb-3 text-lg font-bold">标签</h2>
      <div>
        <Badge variant="default">default</Badge>
        <Badge variant="secondary">secondary</Badge>
        <Badge variant="destructive">destructive</Badge>
        <Badge variant="outline">outline</Badge>
      </div>

      <h2 className="mt-10 mb-3 text-lg font-bold">分页</h2>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="overview">概览</TabsTrigger>
          <TabsTrigger value="files">文件</TabsTrigger>
        </TabsList>
        <TabsContent value="overview">示例内容 A</TabsContent>
        <TabsContent value="files">示例内容 B</TabsContent>
      </Tabs>

      <h2 className="mt-10 mb-3 text-lg font-bold">表格</h2>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>学生</TableHead>
            <TableHead>学校</TableHead>
            <TableHead>顾问</TableHead>
            <TableHead>更新</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((n) => (
            <TableRow key={n}>
              <TableCell>示例学生 {n}</TableCell>
              <TableCell>示例学校</TableCell>
              <TableCell>示例顾问</TableCell>
              <TableCell>2026-11-02</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <h2 className="mt-10 mb-3 text-lg font-bold">菜单与弹窗</h2>
      <div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button>菜单</Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent>
            <DropdownMenuItem>选项一</DropdownMenuItem>
            <DropdownMenuItem>选项二</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Dialog>
          <DialogTrigger asChild>
            <Button>打开对话框</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>对话框</DialogTitle>
              <DialogDescription>示例内容</DialogDescription>
            </DialogHeader>
          </DialogContent>
        </Dialog>
        <Sheet>
          <SheetTrigger asChild>
            <Button>打开侧栏</Button>
          </SheetTrigger>
          <SheetContent>
            <SheetHeader>
              <SheetTitle>对话框</SheetTitle>
            </SheetHeader>
            示例内容
          </SheetContent>
        </Sheet>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button>悬停</Button>
          </TooltipTrigger>
          <TooltipContent>提示内容</TooltipContent>
        </Tooltip>
      </div>

      <h2 className="mt-10 mb-3 text-lg font-bold">加载</h2>
      <Skeleton className="h-4 w-64" />
      <Skeleton className="h-4 w-48" />
      <Skeleton className="h-4 w-32" />
    </div>
  );
}
