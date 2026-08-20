'use client'

import { useApp } from '@/lib/app-context'
import { TaskCard } from './task-card'
import { History } from 'lucide-react'

export function TaskHistoryList() {
  const { state } = useApp()
  const { recentTasks } = state

  if (recentTasks.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 px-4">
        <div className="w-16 h-16 rounded-2xl bg-secondary/50 flex items-center justify-center mb-4">
          <History className="w-8 h-8 text-muted-foreground/50" />
        </div>
        <h3 className="text-sm font-medium text-foreground mb-1">
          История пуста
        </h3>
        <p className="text-xs text-muted-foreground text-center max-w-[200px]">
          Созданные задачи появятся здесь
        </p>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3 lg:gap-3 xl:grid-cols-4">
      {recentTasks.map((task, index) => (
        <TaskCard 
          key={task.task_id} 
          task={task}
          index={index}
        />
      ))}
    </div>
  )
}
