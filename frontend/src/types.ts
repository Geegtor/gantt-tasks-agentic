export interface ApiTask {
  id: string;
  name: string;
  description: string;
  assignee: string;
  duration_days: number;
  predecessor_ids: string[];
  start_date: string;
  end_date: string;
}

export interface ProjectPlan {
  tasks: ApiTask[];
  project_start: string | null;
}
