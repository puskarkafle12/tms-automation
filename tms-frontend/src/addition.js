// Addition.js

import React, { useState } from 'react';

function Addition() {
  // State variables to hold the values of the two numbers and their sum
  const [num1, setNum1] = useState('');
  const [num2, setNum2] = useState('');
  const [sum, setSum] = useState('');

  // Function to handle addition
  const handleAddition = () => {
    const result = parseFloat(num1) + parseFloat(num2);
    setSum(result);
  };

  return (
    <div>
      <h2>Addition</h2>
      <input
        type="number"
        value={num1}
        onChange={(e) => setNum1(e.target.value)}
        placeholder="Enter first number"
      />
      <input
        type="number"
        value={num2}
        onChange={(e) => setNum2(e.target.value)}
        placeholder="Enter second number"
      />
      <button onClick={handleAddition}>Add</button>
      {sum && <p>Sum: {sum}</p>}
    </div>
  );
}

export default Addition;
