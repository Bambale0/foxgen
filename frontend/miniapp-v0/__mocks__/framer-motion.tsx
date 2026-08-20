import React from 'react'

const motionDiv = React.forwardRef((props: any, ref: any) =>
  React.createElement('div', { ref, ...props })
)
const motionSpan = React.forwardRef((props: any, ref: any) =>
  React.createElement('span', { ref, ...props })
)
const motionButton = React.forwardRef((props: any, ref: any) =>
  React.createElement('button', { ref, ...props })
)
const motionImg = React.forwardRef((props: any, ref: any) =>
  React.createElement('img', { ref, ...props })
)
const motionVideo = React.forwardRef((props: any, ref: any) =>
  React.createElement('video', { ref, ...props })
)
const motionSection = React.forwardRef((props: any, ref: any) =>
  React.createElement('section', { ref, ...props })
)
const motionNav = React.forwardRef((props: any, ref: any) =>
  React.createElement('nav', { ref, ...props })
)

export const motion = {
  div: motionDiv,
  span: motionSpan,
  button: motionButton,
  img: motionImg,
  video: motionVideo,
  section: motionSection,
  nav: motionNav,
  ul: React.forwardRef((props: any, ref: any) => React.createElement('ul', { ref, ...props })),
  li: React.forwardRef((props: any, ref: any) => React.createElement('li', { ref, ...props })),
  p: React.forwardRef((props: any, ref: any) => React.createElement('p', { ref, ...props })),
  h1: React.forwardRef((props: any, ref: any) => React.createElement('h1', { ref, ...props })),
  h2: React.forwardRef((props: any, ref: any) => React.createElement('h2', { ref, ...props })),
  h3: React.forwardRef((props: any, ref: any) => React.createElement('h3', { ref, ...props })),
  a: React.forwardRef((props: any, ref: any) => React.createElement('a', { ref, ...props })),
  header: React.forwardRef((props: any, ref: any) => React.createElement('header', { ref, ...props })),
  footer: React.forwardRef((props: any, ref: any) => React.createElement('footer', { ref, ...props })),
  main: React.forwardRef((props: any, ref: any) => React.createElement('main', { ref, ...props })),
  article: React.forwardRef((props: any, ref: any) => React.createElement('article', { ref, ...props })),
  aside: React.forwardRef((props: any, ref: any) => React.createElement('aside', { ref, ...props })),
  form: React.forwardRef((props: any, ref: any) => React.createElement('form', { ref, ...props })),
  input: React.forwardRef((props: any, ref: any) => React.createElement('input', { ref, ...props })),
  textarea: React.forwardRef((props: any, ref: any) => React.createElement('textarea', { ref, ...props })),
  select: React.forwardRef((props: any, ref: any) => React.createElement('select', { ref, ...props })),
  label: React.forwardRef((props: any, ref: any) => React.createElement('label', { ref, ...props })),
  svg: React.forwardRef((props: any, ref: any) => React.createElement('svg', { ref, ...props })),
  path: React.forwardRef((props: any, ref: any) => React.createElement('path', { ref, ...props })),
  circle: React.forwardRef((props: any, ref: any) => React.createElement('circle', { ref, ...props })),
  rect: React.forwardRef((props: any, ref: any) => React.createElement('rect', { ref, ...props })),
  g: React.forwardRef((props: any, ref: any) => React.createElement('g', { ref, ...props })),
}

export { motionDiv as div, motionSpan as span, motionButton as button, motionImg as img }

export const AnimatePresence = ({ children }: any) =>
  React.createElement(React.Fragment, null, children)