'use client'

import { useApp } from '@/lib/app-context'
import { CreateTab } from './tabs/create-tab'
import { HomeTab } from './tabs/home-tab'
import { ModelsTab } from './tabs/models-tab'
import { ProfileTab } from './tabs/profile-tab'
import { ServicesTab } from './tabs/services-tab'
import { WorksTab } from './tabs/works-tab'

export function TabContent() {
  const { activeTab } = useApp()
  if (activeTab === 'models') return <ModelsTab />
  if (activeTab === 'create') return <CreateTab />
  if (activeTab === 'works') return <WorksTab />
  if (activeTab === 'services') return <ServicesTab />
  if (activeTab === 'profile') return <ProfileTab />
  return <HomeTab />
}
