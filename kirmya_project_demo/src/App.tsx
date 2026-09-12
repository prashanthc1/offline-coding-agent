import React, { useState } from 'react';

export interface Task {
  id: number;
  title: string;
  completed: boolean;
}

export const App: React.FC = () => {
  const [tasks, setTasks] = useState<Task[]>([
    { id: 1, title: 'Inspect kirmya_project codebase', completed: true },
    { id: 2, title: 'Run typecheck and unit tests', completed: false },
  ]);

  const toggleTask = (id: number) => {
    setTasks(prev =>
      prev.map(task =>
        task.id === id ? { ...task, completed: !task.completed } : task
      )
    );
  };

  return (
    <div className="container" style={{ padding: '20px', fontFamily: 'sans-serif' }}>
      <h1>kirmya_project Dashboard</h1>
      <p>Offline Coding Agent Target Application</p>
      <ul>
        {tasks.map(task => (
          <li key={task.id} style={{ marginBottom: '8px' }}>
            <label style={{ textDecoration: task.completed ? 'line-through' : 'none' }}>
              <input
                type="checkbox"
                checked={task.completed}
                onChange={() => toggleTask(task.id)}
                style={{ marginRight: '8px' }}
              />
              {task.title}
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
};

export default App;
