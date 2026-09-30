'use client'

import { useState } from 'react'
import { useApp } from '@/lib/app-context'
import { ServiceGrid } from '../service-grid'
import { toast } from 'sonner'
import type { WorkspacePanel } from '@/lib/types'
import { setStorageItem } from '@/hooks/browser-storage'

type ServiceConfig = {
  title: string
  workspace?: WorkspacePanel
  tab?: number
  message: string
}

const serviceMap: Record<string, ServiceConfig> = {
  'prompt-by-photo': {
    title: 'Разобрать фото',
    workspace: 'photo-prompt',
    message: 'Пришли фото — соберём промпт по его стилю и деталям.',
  },
  avatar: {
    title: 'Оживить персонажа',
    tab: 2,
    message: 'Добавь фото персонажа и голос — дальше соберём аватар.',
  },
  'edit-photo': {
    title: 'Изменить кадр',
    tab: 1,
    message: 'Выбери фото и скажи, что хочешь поменять.',
  },
  animate: {
    title: 'Добавить движение',
    tab: 2,
    message: 'Добавь изображение и задай движение будущего ролика.',
  },
  support: {
    title: 'Нужна помощь',
    workspace: 'support',
    message: 'Опиши проблему одним сообщением.',
  },
  partners: {
    title: 'Партнёрка',
    workspace: 'partners',
    message: 'Здесь твоя ссылка, статистика и выплаты.',
  },
  more: {
    title: 'Ещё',
    workspace: 'more',
    message: 'История, настройки и дополнительные возможности — здесь.',
  },
}

export function ServicesTab() {
  const { setActiveTab, openWorkspace } = useApp()
  const [activeService, setActiveService] = useState('prompt-by-photo')

  function runService(serviceId: string) {
    const config = serviceMap[serviceId] || serviceMap['prompt-by-photo']
    setActiveService(serviceId)

    if (serviceId === 'avatar' && typeof window !== 'undefined') {
      setStorageItem('miniapp_requested_video_model', 'avatar_pro')
      setStorageItem('miniapp_requested_video_scenario', 'avatar')
    }

    if (typeof config.tab === 'number') {
      setActiveTab(config.tab)
    }

    if (config.workspace) {
      openWorkspace(config.workspace)
    }

    toast.success(config.title, { description: config.message })
  }

  return (
    <div className="px-4 space-y-5 pb-28">
      <ServiceGrid activeServiceId={activeService} onServiceClick={runService} />
    </div>
  )
}
