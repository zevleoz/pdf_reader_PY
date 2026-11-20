import type { Boot } from '@/lib/boot';
import type { PageData, StudentInfo } from '../profile/common';
import type { WorkspaceContext } from './controller';
export async function bootstrap(sid: string, boot: Boot, signal: AbortSignal): Promise<WorkspaceContext | null> {
  // Account policy gate precedes even metadata resolution; detail never crosses it.
  if (boot.policy.detail_level !== 'full') return null;
  if (!/^\d+$/.test(sid)) throw new Error('学生不存在');
  async function read<T>(path: string): Promise<T> {
    if (signal.aborted) throw new DOMException('已停止', 'AbortError');
    const response = await fetch(path, { credentials: 'same-origin', signal });
    if (!response.ok) throw new Error('无法载入学生（HTTP ' + response.status + '）');
    const data = await response.json();
    if (signal.aborted) throw new DOMException('已停止', 'AbortError');
    if (data.ok === false) throw new Error(data.error || '无法载入学生');
    return data;
  }
  const list = await read<{ students: (StudentInfo & { student_code?: string })[] }>('/api/students');
  const student = list.students.find(row => String(row.id) === sid);
  if (!student) throw new Error('学生不存在或不在当前账号范围内');
  const code = student.code || student.student_code || '';
  if (!code) throw new Error('学生编号不可用');
  const profile = await read<PageData>('/api/profiling/students/' + encodeURIComponent(code));
  if (!profile.permissions.full || profile.first_touch.restricted) return null;
  if (String(profile.student.id) !== sid) throw new Error('学生资料不匹配');
  const canWrite = profile.permissions.can_write && ['admin', 'advisor'].includes(boot.user.role);
  return {
    sid: Number(sid), code, name: student.name || '', grade: student.grade || '',
    school: student.school || '', advisorName: student.advisor_name || '',
    sessionId: profile.first_touch.sessionId, canStart: profile.first_touch.canStart,
    canWrite, readOnly: !canWrite, role: boot.user.role,
  };
}
