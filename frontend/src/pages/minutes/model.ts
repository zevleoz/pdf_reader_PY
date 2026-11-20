export type Student = {
  id: number;
  name: string;
  student_code?: string;
  grade?: string;
  gender?: string;
};
export type Minute = {
  id: number;
  student_id?: number;
  report_id?: number | null;
  transcript_text?: string;
  minutes_text?: string;
  student_name?: string;
  student_grade?: string;
  student_gender?: string;
  created_at?: string;
  preview?: string;
};
export type Draft = {
  transcript: string;
  text: string;
  name: string;
  grade: string;
  gender: string;
  prompt: string;
  id: number | null;
  savedText: string;
  savedTranscript: string;
};
export const emptyDraft = (): Draft => ({ transcript: '', text: '', name: '', grade: '', gender: '', prompt: '', id: null, savedText: '', savedTranscript: '' });
export const changed = (d: Draft) => d.text !== d.savedText || d.transcript !== d.savedTranscript || !!d.prompt;
export const draftKey = (userId: number, sid: string, rid: string) => `minutes-draft:v2:${userId}:${sid || 'unlinked'}:${rid || 'none'}`;
export const displayedText = (d: Draft) => d.text.split('【学生姓名】').join(d.name || '【学生姓名】');
export function readDraft(key: string): Draft | null {
  try {
    const d = JSON.parse(sessionStorage.getItem(key) || 'null');
    if (!d || Object.keys(emptyDraft()).some(k => k !== 'id' && typeof d[k] !== 'string') || !(d.id === null || Number.isInteger(d.id)))
      return null;
    return d;
  }
  catch {
    return null;
  }
}
export function fillMetadata(draft: Draft, student: Student): Draft {
  return { ...draft, name: draft.name || student.name || '', grade: draft.grade || student.grade || '', gender: draft.gender || student.gender || '' };
}
