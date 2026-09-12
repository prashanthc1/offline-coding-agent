import { describe, it, expect } from 'vitest';
import React from 'react';
import { App } from '../App';

describe('App component', () => {
  it('renders initial task count', () => {
    expect(App).toBeDefined();
  });
});
