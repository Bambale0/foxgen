'use client'

import dynamic from 'next/dynamic'
import { useEffect, type ComponentType } from 'react'
import { useApp } from '@/lib/app-context'
import { AnimatePresence, motion } from 'framer-motion'
import { StudioTab } from './tabs/studio-tab'

function TabLoading() {
  return (
    <div className="space-y-3 px-3 py-4 sm:px-4" role="status" aria-label="Загрузка раздела">
      <div className="h-7 w-36 animate-pulse rounded-lg bg-secondary/70" />
      <div className="grid grid-cols-2 gap-3">
        <div className="h-36 animate-pulse rounded-2xl bg-secondary/50" />
        <div className="h-36 animate-pulse rounded-2xl bg-secondary/50" />
      </div>
    </div>
  )
}

const dynamicTab = (loader: () => Promise<{ default: ComponentType }>) =>
  dynamic(loader, { loading: TabLoading })

const PhotoTab = dynamicTab(() => import('./tabs/photo-tab').then((module) => ({ default: module.PhotoTab })))
const VideoTab = dynamicTab(() => import('./tabs/video-tab').then((module) => ({ default: module.VideoTab })))
const MotionTab = dynamicTab(() => import('./tabs/motion-tab').then((module) => ({ default: module.MotionTab })))
const FeedTab = dynamicTab(() => import('./tabs/feed-tab').then((module) => ({ default: module.FeedTab })))
const TrendsTab = dynamicTab(() => import('./tabs/trends-tab').then((module) => ({ default: module.TrendsTab })))
const ServicesTab = dynamicTab(() => import('./tabs/services-tab').then((module) => ({ default: module.ServicesTab })))
const ProfileTab = dynamicTab(() => import('./tabs/profile-tab').then((module) => ({ default: module.ProfileTab })))

const tabComponents = [StudioTab, PhotoTab, VideoTab, MotionTab, FeedTab, TrendsTab, ServicesTab, ProfileTab]

export function TabContent() {
  const { activeTab } = useApp()
  const ActiveComponent = tabComponents[activeTab] || StudioTab

  useEffect(() => {
    const prefetchTimer = window.setTimeout(() => {
      void import('./tabs/feed-tab')
    }, 800)
    return () => window.clearTimeout(prefetchTimer)
  }, [])

  return (
    <div className="relative">
      <AnimatePresence mode="wait">
        <motion.div
          key={activeTab}
          initial={false}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ 
            duration: 0.25, 
            ease: [0.25, 0.46, 0.45, 0.94] 
          }}
        >
          <ActiveComponent />
        </motion.div>
      </AnimatePresence>
    </div>
  )
}
