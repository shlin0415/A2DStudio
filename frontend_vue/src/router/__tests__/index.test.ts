import { describe, expect, it } from 'vitest'
import router from '../index'

describe('A2D Studio route', () => {
  it('exposes the studio at its product route without the old stage URL', () => {
    const studioRoute = router.getRoutes().find((route) => route.name === 'A2DStudio')

    expect(studioRoute?.path).toBe('/studio')
    expect(router.resolve('/stage').matched).toHaveLength(0)
  })
})
