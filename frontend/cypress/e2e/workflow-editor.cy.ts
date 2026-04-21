describe('Workflow editor core flow', () => {
  it('loads edit page and shows key actions', () => {
    cy.intercept('GET', '**/api/v1/workflows/wf-demo', {
      statusCode: 200,
      body: {
        workflow_id: 'wf-demo',
        name: 'Demo Workflow',
        latest_version_id: 'v1',
        published_version_id: 'v1',
      },
    }).as('getWorkflow')

    cy.intercept('GET', '**/api/v1/workflows/wf-demo/versions/v1', {
      statusCode: 200,
      body: {
        version_id: 'v1',
        dag: {
          nodes: [{ id: 'start', type: 'start', name: 'Start', config: {}, position: { x: 80, y: 120 } }],
          edges: [],
        },
      },
    }).as('getVersion')

    cy.visit('/workflow/wf-demo/edit')
    cy.wait('@getWorkflow')
    cy.wait('@getVersion')

    cy.contains('运行前检查').should('be.visible')
    cy.contains('保存为新版本').should('be.visible')
    cy.get('aside[aria-label="节点库面板"]').should('exist')
    cy.get('aside[aria-label="节点配置面板"]').should('exist')
  })
})
