'use client'

import { BookImage, CircleDollarSign, Headphones, Newspaper, ReceiptText, UsersRound } from 'lucide-react'
import { useApp } from '@/lib/app-context'

export function ServicesTab() {
  const { openWorkspace, bootstrap } = useApp()
  const services = [
    { id: 'balance' as const, title: 'Баланс и Stars', subtitle: `${(bootstrap?.balance.available_units ?? 0).toLocaleString('ru-RU')} CREDIT`, icon: CircleDollarSign },
    { id: 'feed' as const, title: 'Сообщество', subtitle: 'Лента, лайки и remix', icon: Newspaper },
    { id: 'references' as const, title: 'Референсы', subtitle: 'Память изображений', icon: BookImage },
    { id: 'tariff' as const, title: 'Тарифы', subtitle: 'Условия из backend', icon: ReceiptText },
    { id: 'partner' as const, title: 'Партнёры', subtitle: 'Рефералы и выплаты', icon: UsersRound },
    { id: 'support' as const, title: 'Поддержка', subtitle: 'Тикеты и ответы', icon: Headphones },
  ]
  return (
    <main className="page" data-testid="screen-services">
      <section className="hero"><span className="eyebrow">SERVICES</span><h1>Все <span>сервисы</span></h1><p>Пользовательский backend вне генераций: платежи, лента, референсы, тарифы, партнёрская программа и поддержка.</p></section>
      <section className="section service-grid">
        {services.map((item) => {
          const Icon = item.icon
          return <button className="service-card" data-testid={`service-${item.id}`} key={item.id} onClick={() => openWorkspace(item.id)}><span><Icon size={23}/></span><strong>{item.title}</strong><small>{item.subtitle}</small></button>
        })}
      </section>
    </main>
  )
}
